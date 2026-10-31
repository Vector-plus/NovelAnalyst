"""F 类 · 审计检查工具（AuditAnalyzeReActAgent 用）。

对应《04-prompt_审查.md》§0.2 / 《03-核心图设计_索引生成.md》§5.7：5 个检查工具
均为**确定性、只读、不依赖 LLM**，返回结构化命中结果（JSON 字符串）。

迁移自 demo ``audit_simple.py``，修正：
- C1 · novel_root 参数化（demo 硬编码环境变量 AUDIT_NOVEL_ROOT）。
- C2 · ``check_stage_integrity`` 检查 ``_staging/stages/{stage_id}.commit.json``
  （P2c 的实际落盘位置），非 demo 的 ``_staging/deepread/stages/``。
- C3 · ``check_id_conflict`` 不报「空号」：03 §4.7 明确「先分配后写文件允许空号」，
  空号非冲突；只报「重复」与「超发」（文件最大编号 > 高水位）。
- C4 · 复用 ``common.load_json``，写盘统一走 fingerprint 规范（本模块只读，不写）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from langchain_core.tools import tool

from deerflow_simple.index_builder.tools.common import load_json

# check_ref_reachability 需要扫描的根索引文件（其 entries[].target / entity_refs
# 是主要 Ref 来源）。文件不存在时 load_json 返回 None 自动跳过，列表可保守偏全。
_ROOT_INDEX_FILES = [
    "characters/index.json",
    "events/index.json",
    "relationships/index.json",
    "emotions/index.json",
    "factions/index.json",
    "plot/index.json",
    "settings/index.json",
    "threads/index.json",
    "quality/issues.json",
    "quality/coverage.json",
    "navigation/chapters/index.json",
    "navigation/names/index.json",
]


def _read_text(root: Path, rel_path: str) -> str:
    full = root / rel_path
    if not full.is_file():
        return ""
    return full.read_text(encoding="utf-8", errors="replace")


def _max_committed_chapter(root: Path) -> int:
    """从 ledger 推断已 committed 的最大章号（check_stage_integrity 用）。"""
    max_ch = 0
    ledger_dir = root / "ledger" / "chapters"
    if not ledger_dir.is_dir():
        return max_ch
    for fname in sorted(ledger_dir.iterdir()):
        if not fname.name.startswith("ch-") or not fname.name.endswith(".json"):
            continue
        data = load_json(root, f"ledger/chapters/{fname.name}")
        if data and data.get("status") == "committed":
            ch = data.get("chapter_ref", {}).get("chapter_order", 0)
            max_ch = max(max_ch, ch)
    return max_ch


def _iter_event_blocks(root: Path):
    events_dir = root / "events"
    if not events_dir.is_dir():
        return
    for fname in sorted(events_dir.iterdir()):
        if fname.name.startswith("block-") and fname.name.endswith(".json"):
            yield f"events/{fname.name}"


def _check_ref(root: Path, ref: dict, src: str, acc: list) -> None:
    """校验单个 Ref 的 path 可达 + record_id 可达，不可达则追加到 acc。"""
    if not isinstance(ref, dict):
        return
    path = ref.get("path")
    if not path:
        return
    record_id = ref.get("record_id")
    full = root / path
    if not full.is_file():
        acc.append({"record_ref": ref, "from": src, "problem": f"path 文件不存在: {path}"})
        return
    # 原文引用（source/ 开头）只校验 path 存在，不校验 record_id
    if record_id and not path.startswith("source/"):
        if record_id not in _read_text(root, path):
            acc.append({"record_ref": ref, "from": src,
                        "problem": f'record_id "{record_id}" 不在目标文件 {path} 中'})


def build_audit_tools(novel_root: str) -> list:
    root = Path(novel_root)

    @tool
    def check_ref_reachability() -> str:
        """校验索引产物中所有 Ref 的 path 可达 + record_id 可达，返回不可达清单。

        返回 JSON 字符串：{"check": "check_ref_reachability", "hit_count": N, "hits": [...]}
        每个 hit 含 record_ref、from（引用来源文件）、problem。
        """
        unreachable: list = []
        for rel in _ROOT_INDEX_FILES:
            idx = load_json(root, rel)
            if not idx:
                continue
            for e in idx.get("entries", []):
                _check_ref(root, e.get("target", {}), rel, unreachable)
                for r in e.get("entity_refs", []):
                    _check_ref(root, r, rel, unreachable)
        manifest = load_json(root, "manifest.json")
        if manifest:
            for key, val in manifest.items():
                if isinstance(val, dict) and "path" in val:
                    _check_ref(root, val, "manifest.json", unreachable)
        for rel in _iter_event_blocks(root):
            block = load_json(root, rel)
            if not block:
                continue
            for ev in block.get("events", []):
                for upd in ev.get("updates", []):
                    for p in upd.get("participants", []):
                        _check_ref(root, p.get("entity_ref", {}), rel, unreachable)
                    for c in upd.get("claims", []):
                        at = c.get("attributed_to_ref")
                        if at:
                            _check_ref(root, at, rel, unreachable)
                        for r in (c.get("basis_refs") or []) + (c.get("supersedes_refs") or []):
                            _check_ref(root, r, rel, unreachable)
                    for r in ((upd.get("trigger_refs") or []) + (upd.get("action_refs") or [])
                              + (upd.get("outcome_refs") or []) + (upd.get("related_event_refs") or [])):
                        _check_ref(root, r, rel, unreachable)
        return json.dumps({"check": "check_ref_reachability",
                           "hit_count": len(unreachable), "hits": unreachable}, ensure_ascii=False)

    @tool
    def check_orphan_claims() -> str:
        """校验 events 中 entity_ref / attributed_to_ref 指向的实体是否已建档（孤儿检测）。

        返回 JSON 字符串：{"check": "check_orphan_claims", "hit_count": N, "hits": [...]}
        """
        orphans: list = []
        entity_ids: set = set()
        chars_idx = load_json(root, "characters/index.json") or {"entries": []}
        for e in chars_idx.get("entries", []):
            rid = e.get("target", {}).get("record_id")
            if rid:
                entity_ids.add(rid)

        for rel in _iter_event_blocks(root):
            block = load_json(root, rel)
            if not block:
                continue
            for ev in block.get("events", []):
                for upd in ev.get("updates", []):
                    for p in upd.get("participants", []):
                        ref = p.get("entity_ref", {})
                        rid = ref.get("record_id")
                        if rid and rid not in entity_ids:
                            orphans.append({"record_ref": ref, "event_id": ev.get("id"),
                                            "problem": f"参与实体 {rid} 未建档（孤儿引用）"})
                    for c in upd.get("claims", []):
                        at = c.get("attributed_to_ref")
                        if at:
                            rid = at.get("record_id")
                            if rid and rid not in entity_ids:
                                orphans.append({"record_ref": at, "claim_id": c.get("id"),
                                                "problem": f"归因实体 {rid} 未建档（孤儿引用）"})
        return json.dumps({"check": "check_orphan_claims",
                           "hit_count": len(orphans), "hits": orphans}, ensure_ascii=False)

    @tool
    def check_cutoff_leak() -> str:
        """校验 events 中 update/claim 的 revealed_at 是否超过所在 event/block 的 safe_through（时间泄漏）。

        返回 JSON 字符串：{"check": "check_cutoff_leak", "hit_count": N, "hits": [...]}
        """
        leaks: list = []
        for rel in _iter_event_blocks(root):
            block = load_json(root, rel)
            if not block:
                continue
            block_st = block.get("safe_through", 0)
            for ev in block.get("events", []):
                ev_st = ev.get("safe_through", 0)
                for upd in ev.get("updates", []):
                    ra = upd.get("revealed_at")
                    if ra is not None and ev_st and ra > ev_st:
                        leaks.append({"record_id": upd.get("id"), "event_id": ev.get("id"),
                                      "revealed_at": ra, "safe_through": ev_st,
                                      "problem": "update revealed_at > event safe_through"})
                    if ra is not None and block_st and ra > block_st:
                        leaks.append({"record_id": upd.get("id"), "event_id": ev.get("id"),
                                      "revealed_at": ra, "safe_through": block_st,
                                      "problem": "update revealed_at > block safe_through"})
                    for c in upd.get("claims", []):
                        cra = c.get("revealed_at")
                        if cra is not None and ev_st and cra > ev_st:
                            leaks.append({"record_id": c.get("id"), "event_id": ev.get("id"),
                                          "revealed_at": cra, "safe_through": ev_st,
                                          "problem": "claim revealed_at > event safe_through"})
                        if cra is not None and block_st and cra > block_st:
                            leaks.append({"record_id": c.get("id"), "event_id": ev.get("id"),
                                          "revealed_at": cra, "safe_through": block_st,
                                          "problem": "claim revealed_at > block safe_through"})
        return json.dumps({"check": "check_cutoff_leak",
                           "hit_count": len(leaks), "hits": leaks}, ensure_ascii=False)

    @tool
    def check_stage_integrity() -> str:
        """校验已完整精读的 stage 是否已聚合归档（存在 _staging/stages/{stage_id}.commit.json）。

        返回 JSON 字符串：{"check": "check_stage_integrity", "hit_count": N, "hits": [...]}
        """
        issues: list = []
        sp = load_json(root, "navigation/stage-plan.json") or {"stages": []}
        max_ch = _max_committed_chapter(root)
        staging_stages = root / "_staging" / "stages"
        for st in sp.get("stages", []):
            ranges = st.get("chapter_ranges", [])
            if not ranges:
                continue
            end = ranges[-1]["end"]
            stage_id = st.get("id")
            if end <= max_ch:
                commit_path = staging_stages / f"{stage_id}.commit.json"
                if not commit_path.is_file():
                    issues.append({"stage_id": stage_id, "chapter_ranges": ranges,
                                   "problem": f"stage 已完整精读（end={end} <= 已精读最大章 {max_ch}）但缺少 commit.json"})
        return json.dumps({"check": "check_stage_integrity",
                           "hit_count": len(issues), "hits": issues}, ensure_ascii=False)

    @tool
    def check_id_conflict() -> str:
        """校验 ledger 高水位与实际 record_id 一致（只报重复 + 超发，不报空号）。

        返回 JSON 字符串：{"check": "check_id_conflict", "hit_count": N, "hits": [...]}
        """
        conflicts: list = []
        id_state = load_json(root, "ledger/id-state.json") or {"high_watermarks": {}}
        hw = id_state.get("high_watermarks", {})

        claim_ids: list = []
        ev_ids: list = []
        update_ids: list = []
        for rel in _iter_event_blocks(root):
            block = load_json(root, rel)
            if not block:
                continue
            for ev in block.get("events", []):
                ev_ids.append(ev.get("id"))
                for upd in ev.get("updates", []):
                    update_ids.append(upd.get("id"))
                    for c in upd.get("claims", []):
                        claim_ids.append(c.get("id"))

        char_ids: list = []
        chars_idx = load_json(root, "characters/index.json") or {"entries": []}
        for e in chars_idx.get("entries", []):
            rid = e.get("target", {}).get("record_id")
            if rid:
                char_ids.append(rid)

        for label, ids in [("char", char_ids), ("claim", claim_ids),
                           ("ev", ev_ids), ("update", update_ids)]:
            valid = [x for x in ids if x]
            dup = sorted({x for x in valid if valid.count(x) > 1})
            if dup:
                conflicts.append({"kind": label, "problem": f"重复 record_id: {dup}"})
            nums = []
            for x in valid:
                m = re.match(rf"^{label}-(\d+)$", x)
                if m:
                    nums.append(int(m.group(1)))
            if nums:
                mx = max(nums)
                watermark = hw.get(label, 0)
                # 只报「超发」（文件编号超过高水位 = ID 分配 bug）；空号（mx < watermark）
                # 是 03 §4.7 允许的，不报。
                if mx > watermark:
                    conflicts.append({"kind": label,
                                      "problem": f"最大编号 {label}-{mx:04d} 超过高水位 {watermark}"})
        return json.dumps({"check": "check_id_conflict",
                           "hit_count": len(conflicts), "hits": conflicts}, ensure_ascii=False)

    return [
        check_ref_reachability,
        check_orphan_claims,
        check_cutoff_leak,
        check_stage_integrity,
        check_id_conflict,
    ]
