"""deepread 节点 —— 逐章精读 + 边界章 stage 聚合（P2 核心节点）。

对应设计文档《03-核心图设计_索引生成.md》§2.2 N5 + 《04-prompt_第二阶段精读.md》§3。

编排（串行 while 循环）：
1. 游标从 1 开始，每章先查 ledger 四态：``committed`` 则跳过（D5 ① 章节级幂等）。
2. 未 committed：调 ChapterReActAgent 精读 → IndexWriter 落库 → ledger 四态流转
   （prepared → extracted → applying → committed）。
3. 边界章（stage 尾章）触发 StageCommitReActAgent 聚合 stage buffer → 写 stage.md。
4. 每章后更新进度文件 + manifest.published_through；连续 ≥3 章失败则 halt。

恢复语义（决策 5 + 断点恢复，见 restore.py / graph.py build_initial_state）：
- resume/repair 模式：``cursor`` 从 ``state.current_chapter``（restore 推断出的第一个
  未 committed 章）续跑，不再从 1 重扫；已 committed 章仍 O(1) 跳过（双保险）。
- full 模式：``cursor`` 从 1 从头遍历。
- 一期不精确复用 applying 中途失败的 allocated_ids（留空号，由 audit 兜底），
  仅靠「committed 跳过」这道闸保证不重复定义已提交记录（见 AGENT.md D5）。

完成与 halt 语义：
- 正常跑完全书 → ``phase="audit"``（进入 N6 审计）。
- halt（error_limit 等）→ ``phase="done"`` + ``halt_reason``，任务中止；用户重新
  POST 任务（build_mode=resume）时靠 ledger 幂等跳过已 committed 章续跑。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from deerflow_simple.config import SimpleConfig
from deerflow_simple.index_builder.agents.chapter_react import (
    build_chapter_react_agent,
    build_chapter_react_prompt,
)
from deerflow_simple.index_builder.agents.runner import run_agent_streaming
from deerflow_simple.index_builder.agents.schemas import ChapterExtraction, StageCommitPayload
from deerflow_simple.index_builder.agents.stage_commit_react import (
    build_stage_commit_react_agent,
    build_stage_commit_react_prompt,
)
from deerflow_simple.index_builder.state import BuildState
from deerflow_simple.index_builder.tools.common import build_chapter_index, load_json
from deerflow_simple.index_builder.writes.index_writer import IndexWriter
from deerflow_simple.index_builder.writes.ledger import (
    STATUS_APPLYING,
    STATUS_EXTRACTED,
    LedgerService,
)

# Agent 缓存：按 novel_root 复用编译好的 graph（无状态，可安全复用）。
_chapter_agent_cache: dict[str, object] = {}
_stage_commit_agent_cache: dict[str, object] = {}

# staging 目录（相对 novel_root）
_STAGING_DIR = "_staging"
# 每章 LLM 抽取的最大重试次数（04-prompt §3.3：单章 ≤3 次）
_CHAPTER_MAX_RETRY = 3
# 连续失败章数阈值（03 §2.2 N5：连续 ≥3 章失败 → error_limit）
_ERROR_LIMIT = 3


def _get_chapter_agent(config: SimpleConfig, novel_root: str):
    if novel_root not in _chapter_agent_cache:
        _chapter_agent_cache[novel_root] = build_chapter_react_agent(config, novel_root)
    return _chapter_agent_cache[novel_root]


def _get_stage_commit_agent(config: SimpleConfig, novel_root: str):
    if novel_root not in _stage_commit_agent_cache:
        _stage_commit_agent_cache[novel_root] = build_stage_commit_react_agent(config, novel_root)
    return _stage_commit_agent_cache[novel_root]


def _parse_json(text: str) -> dict:
    """从 Agent 输出里提取 JSON 对象（容错剥离外围文本 / markdown 代码块）。"""
    text = (text or "").strip()
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        text = m.group(0)
    return json.loads(text)


def _build_stage_index(novel_root: str) -> dict[int, dict]:
    """构建 chapter_order -> stage 映射（读 confirmed stage-plan）。"""
    root = Path(novel_root)
    sp = load_json(root, "navigation/stage-plan.json") or {"stages": []}
    by_chapter: dict[int, dict] = {}
    for st in sp.get("stages", []):
        for r in st.get("chapter_ranges", []):
            for ch in range(r.get("start", 1), r.get("end", 0) + 1):
                by_chapter[ch] = st
    return by_chapter


def _staging_path(novel_root: str, rel: str) -> Path:
    full = Path(novel_root) / _STAGING_DIR / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    return full


def _append_stage_buffer(novel_root: str, stage_id: str, chapter_order: int, appends: list) -> None:
    if not appends:
        return
    path = _staging_path(novel_root, f"stages/{stage_id}.buffer.jsonl")
    with path.open("a", encoding="utf-8") as f:
        for item in appends:
            item = dict(item)
            item.setdefault("chapter_order", chapter_order)
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def _load_stage_buffer(novel_root: str, stage_id: str) -> list:
    path = Path(novel_root) / _STAGING_DIR / f"stages/{stage_id}.buffer.jsonl"
    if not path.is_file():
        return []
    items = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def _write_progress(novel_root: str, current_chapter: int, total: int, published_through: int, halt_reason: str | None) -> None:
    """写独立进度文件（决策 4：query_build_status 轮询此文件，不依赖 graph checkpoint）。"""
    progress = {
        "current_chapter": current_chapter,
        "total_chapters": total,
        "published_through": published_through,
        "halt_reason": halt_reason,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _staging_path(novel_root, "progress.json").write_text(
        json.dumps(progress, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _update_published_through(novel_root: str, chapter_order: int) -> None:
    """更新 manifest.published_through（串行顺序处理，连续前缀 = 当前章）。"""
    root = Path(novel_root)
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["published_through"] = chapter_order
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def make_deepread_node(config: SimpleConfig):
    """构造 deepread 节点函数（闭包捕获 config）。"""

    async def deepread_node(state: BuildState) -> BuildState:
        novel_root = state["novel_root"]
        novel_id = state["novel_id"]
        source_version = state["source_version"]
        total = state["total_chapters"]
        if total <= 0:
            return {"phase": "done", "halt_reason": None}

        chapter_index = build_chapter_index(novel_root)
        stage_by_chapter = _build_stage_index(novel_root)
        ledger_service = LedgerService(novel_root, novel_id, source_version)
        writer = IndexWriter(novel_root, novel_id, source_version)
        chapter_agent = _get_chapter_agent(config, novel_root)
        stage_agent = _get_stage_commit_agent(config, novel_root)

        # known_entities_digest：从 stage-plan character_candidates 提取（仅导航参考）
        known_entities_digest = ""
        sp = load_json(Path(novel_root), "navigation/stage-plan.json") or {}
        candidates = sp.get("character_candidates", [])
        if candidates:
            known_entities_digest = json.dumps(candidates[:50], ensure_ascii=False, indent=2)

        error_count = 0
        processed = 0
        halt_reason = None
        published_through = 0

        # 恢复起点：resume 时从 state.current_chapter（restore 推断出的「第一个未
        # committed 章」）续跑；full 时为 1。即使恢复起点略靠前，已 committed 章仍会
        # 被下方 is_committed 跳过（双保险）。
        cursor = state.get("current_chapter") or 1
        if cursor < 1:
            cursor = 1
        while cursor <= total:
            info = chapter_index.get(cursor)
            if info is None:
                cursor += 1
                continue
            chapter_id = info["chapter_id"]

            # ① 章节级幂等（D5 ①）：committed 章直接跳过
            if ledger_service.is_committed(chapter_id):
                published_through = cursor
                cursor += 1
                continue

            stage = stage_by_chapter.get(cursor, {"id": "stage-000", "title": "未知",
                                                  "chapter_ranges": [{"start": cursor, "end": cursor}]})
            stage_id = stage["id"]
            stage_ranges = stage.get("chapter_ranges", [{"start": cursor, "end": cursor}])
            stage_start = stage_ranges[0]["start"]
            stage_end = stage_ranges[-1]["end"]
            position_in_stage = cursor - stage_start + 1
            stage_chapter_count = stage_end - stage_start + 1

            # ② LLM 精读（失败重试 ≤3）
            extraction = None
            for attempt in range(1, _CHAPTER_MAX_RETRY + 1):
                try:
                    prompt = build_chapter_react_prompt(
                        novel_root,
                        source_version,
                        cursor,
                        chapter_id,
                        stage_id,
                        stage_start,
                        stage_end,
                        position_in_stage,
                        stage_chapter_count,
                        known_entities_digest=known_entities_digest,
                    )
                    text = await run_agent_streaming(chapter_agent, prompt, config)
                    extraction = ChapterExtraction.model_validate(_parse_json(text)).model_dump()
                    break
                except Exception as exc:  # noqa: BLE001
                    if attempt >= _CHAPTER_MAX_RETRY:
                        error_count += 1
                        if error_count >= _ERROR_LIMIT:
                            halt_reason = "error_limit"
                        break
            if extraction is None:
                if halt_reason:
                    break
                cursor += 1
                continue

            # ③ 落库 + ledger 四态流转
            try:
                ledger_service.prepare(chapter_id, cursor)
                allocated_ids = writer.write_chapter(cursor, extraction)
                ledger_service.record_extraction(
                    chapter_id, allocated_ids, f"第{cursor}章精读完成", list(allocated_ids)
                )
                ledger_service.transition(chapter_id, STATUS_EXTRACTED, STATUS_APPLYING)
                ledger_service.commit(chapter_id)
            except Exception as exc:  # noqa: BLE001
                error_count += 1
                if error_count >= _ERROR_LIMIT:
                    halt_reason = "error_limit"
                    break
                cursor += 1
                continue

            # ④ 追加 stage buffer
            _append_stage_buffer(novel_root, stage_id, cursor, extraction.get("stage_buffer_appends", []))

            # ⑤ 边界章触发 stage 聚合
            if cursor == stage_end:
                try:
                    await _commit_stage(
                        config, novel_root, novel_id, source_version, total,
                        stage, stage_agent, writer,
                    )
                except Exception:  # noqa: BLE001 - stage 聚合失败不阻断主循环
                    pass

            # ⑥ 进度推进
            error_count = 0
            processed += 1
            published_through = cursor
            _update_published_through(novel_root, cursor)
            _write_progress(novel_root, cursor, total, published_through, halt_reason)
            cursor += 1

        # 收尾：写最终进度
        _write_progress(novel_root, min(cursor - 1, total), total, published_through, halt_reason)

        # 正常完成 → audit（N6）；halt（error_limit 等）→ done（构建中止）
        phase = "audit" if halt_reason is None else "done"

        return {
            "phase": phase,
            "current_chapter": None,
            "published_through": published_through,
            "halt_reason": halt_reason,
            "metrics": {"chapters_processed": processed},
        }

    return deepread_node


async def _commit_stage(config, novel_root, novel_id, source_version, total, stage, stage_agent, writer) -> None:
    """聚合单个 stage 的 buffer，调 StageCommitReActAgent，写 stage 级产物。"""
    stage_id = stage["id"]
    stage_title = stage.get("title", stage_id)
    ranges = stage.get("chapter_ranges", [{"start": 1, "end": 1}])
    stage_start = ranges[0]["start"]
    stage_end = ranges[-1]["end"]

    buffer = _load_stage_buffer(novel_root, stage_id)
    if not buffer:
        return

    prompt = build_stage_commit_react_prompt(
        novel_root,
        novel_id,
        source_version,
        total,
        stage_id,
        stage_title,
        stage_start,
        stage_end,
        stage_buffer_json=json.dumps(buffer, ensure_ascii=False, indent=2),
    )

    # 整 stage 重试 ≤2（04 §3.3）
    payload = None
    for _ in range(2):
        try:
            text = await run_agent_streaming(stage_agent, prompt, config)
            payload = StageCommitPayload.model_validate(_parse_json(text)).model_dump()
            break
        except Exception:  # noqa: BLE001
            continue
    if payload is None:
        return

    writer.write_stage_commit(stage, payload)
    # 落盘 commit 结果到 _staging 作调试参考
    _staging_path(novel_root, f"stages/{stage_id}.commit.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
