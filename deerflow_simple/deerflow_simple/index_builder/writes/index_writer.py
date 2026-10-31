"""IndexWriter —— 确定性落库器（D 类 · 仅节点函数调用）。

迁移自 ``design/doc/index_create/index_writer.py``，把 ChapterExtraction /
StageCommitPayload 按 templates v2.0 写入正式索引目录。**不依赖 LLM**，只做确定性
转换与写盘（对应 03 文档 §5.10「写入全走确定性路径」）。

对 demo 的修正（对应 index_builder/AGENT.md 决策）：
- C1 · 写盘规范统一：demo ``_write_json`` 无 ``sort_keys``，但 skeleton 与
  services/fingerprint 均用 ``sort_keys=True``。指纹必须一致，故写盘改用
  ``fingerprint.json_bytes``（键按 Unicode 码点排序）+ ``markdown_bytes``。
- C2 · 不写 ledger：demo ``_write_chapter_ledger`` 直接写 ``committed``（无四态）。
  本类不再写 ``ledger/chapters/*.json``，由 deepread 节点用 LedgerService 流转；
  ``write_chapter`` 返回本次分配的 ``allocated_ids`` 供节点写入 ledger。
- C3 · NameIndex 锚定 name_catalog（P2a 已纠正 demo 从 characters 反推）。
- C4 · 修复 demo ``_append_entity_stage_entry`` 的硬编码 stage 序号 bug。
- C5 · relationship/emotional 兼容 04-prompt §2.2 的 ``snapshot`` 嵌套 schema。
- C6 · allocated_ids 完整收集（demo 只收 claim/ev，漏 char/setting/rel/thread）。

一期边界（对齐决策 D5）：内容级语义去重（③）留桩，本类只做 record_id 判重（②）。
"""

from __future__ import annotations

from pathlib import Path

from deerflow_simple.index_builder.services.fingerprint import json_bytes, markdown_bytes
from deerflow_simple.index_builder.services.id_allocator import IdAllocator
from deerflow_simple.index_builder.services.name_index import NameIndex
from deerflow_simple.index_builder.tools.common import build_chapter_index, load_json

# 设定分类受控值（templates §3.8）
_SETTING_CATEGORIES = {
    "power_system", "ability", "artifact", "geography",
    "species", "social_rule", "other",
}


def _filemeta(novel_id: str, record_id: str, kind: str, safe_through: int, revision: int = 1) -> dict:
    """公共文件头 FileMeta（templates §3.1）。"""
    return {
        "schema_version": "2.0",
        "novel_id": novel_id,
        "id": record_id,
        "kind": kind,
        "revision": revision,
        "safe_through": safe_through,
    }


def _ref(path: str, record_id: str) -> dict:
    """引用 Ref（templates §3.3）。"""
    return {"path": path, "record_id": record_id}


class IndexWriter:
    """把结构化提取结果确定性落库到索引目录。"""

    def __init__(
        self,
        novel_root: str,
        novel_id: str,
        source_version: str,
        stage_plan_revision: int = 1,
    ):
        self.root = Path(novel_root)
        self.novel_id = novel_id
        self.source_version = source_version
        self.stage_plan_revision = stage_plan_revision
        self.id_alloc = IdAllocator(novel_root, novel_id)
        self.name_index = NameIndex(novel_root, novel_id)
        self.stage_plan = load_json(self.root, "navigation/stage-plan.json") or {"stages": []}
        # stage_id -> 序号（1 起），用于 block 分片编号与 stage 文件编号
        self._stage_order = {st["id"]: i + 1 for i, st in enumerate(self.stage_plan.get("stages", []))}
        # 章节索引（懒加载缓存）
        self._chapter_index: dict[int, dict] | None = None
        # 本章运行期映射（跨函数共享）
        self._local_to_real: dict[str, str] = {}
        self._name_to_ref: dict[str, dict] = {}
        self._pair_rel_map: dict[tuple, str] = {}
        self._current_block_id: str = "block-0001"
        self._allocated_ids: list[str] = []

    # ==================== 基础辅助 ====================
    def _write_json(self, rel_path: str, obj: dict) -> None:
        full = self.root / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(json_bytes(obj))

    def _write_markdown(self, rel_path: str, text: str) -> None:
        full = self.root / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(markdown_bytes(text))

    def _allocate(self, namespace: str, count: int) -> list[str]:
        """分配 ID 并记入本章 allocated_ids（C6：完整收集）。"""
        ids = self.id_alloc.allocate(namespace, count)
        self._allocated_ids.extend(ids)
        return ids

    def _chapter_index_for(self) -> dict[int, dict]:
        if self._chapter_index is None:
            self._chapter_index = build_chapter_index(str(self.root))
        return self._chapter_index

    def _stage_of(self, chapter_order: int) -> dict:
        for st in self.stage_plan.get("stages", []):
            for r in st.get("chapter_ranges", []):
                if r.get("start", 0) <= chapter_order <= r.get("end", 0):
                    return st
        return {"id": "stage-000", "title": "未知", "chapter_ranges": [{"start": chapter_order, "end": chapter_order}]}

    def _block_id_for_stage(self, stage_id: str) -> str:
        order = self._stage_order.get(stage_id, 1)
        return f"block-{order:04d}"

    def _resolve_name_ref(self, name: str) -> dict | None:
        """名字 → 实体 Ref（已建档），否则 None。用 NameIndex（锚定 name_catalog）。"""
        if name in self._name_to_ref:
            return self._name_to_ref[name]
        refs = self.name_index.resolve_refs(name)
        if refs:
            self._name_to_ref[name] = refs[0]
            return refs[0]
        return None

    def _ensure_char_ref(self, name: str, introduced_at: int) -> dict:
        """为名字解析或新建人物实体，返回其 Ref。"""
        if name in self._name_to_ref:
            return self._name_to_ref[name]
        ref = self._resolve_name_ref(name)
        if ref is not None:
            return ref
        char_id = self._allocate("char", 1)[0]
        self.name_index.register(
            name,
            _ref(f"characters/{char_id}/index.json", char_id),
            entity_type="character",
            name_type="name",
            identity_status="candidate",
            revealed_at=introduced_at,
        )
        self._create_entity_index(char_id, introduced_at, name)
        ref = _ref(f"characters/{char_id}/index.json", char_id)
        self._name_to_ref[name] = ref
        return ref

    def _create_entity_index(self, char_id: str, introduced_at: int, label: str) -> None:
        doc = _filemeta(self.novel_id, char_id, "entity_index", introduced_at) | {
            "entity_type": "character",
            "label": label,
            "introduced_at": introduced_at,
            "identity_notes": [],
            "identity_links": [],
            "related_materials": [],
            "entries": [],
        }
        self._write_json(f"characters/{char_id}/index.json", doc)
        self._append_root_entry("characters", char_id, "entity_index", label, introduced_at, "character")

    def _local_ids_to_refs(self, local_ids: list) -> list:
        refs = []
        for lid in (local_ids or []):
            real = self._local_to_real.get(lid)
            if real:
                refs.append(_ref(f"events/{self._current_block_id}.json", real))
        return refs

    def _topic_target_path(self, topic: str, record_id: str) -> str:
        if topic == "characters":
            return f"characters/{record_id}/index.json"
        if topic == "events":
            return f"events/{record_id}.json"
        if topic == "settings":
            return f"settings/entries/{record_id}.json"
        if topic == "relationships":
            return f"relationships/pairs/{record_id}.json"
        if topic == "threads":
            return f"threads/{record_id}.json"
        if topic == "factions":
            return f"factions/{record_id}/index.json"
        if topic == "emotions":
            return f"emotions/{record_id}/index.json"
        if topic == "plot":
            return f"plot/arcs/{record_id[len('doc-'):]}.md"
        return f"{topic}/{record_id}.json"

    def _append_root_entry(self, topic: str, record_id: str, kind: str, title: str, chapter_order: int, tag: str) -> None:
        """向主题根 index.json 追加 IndexEntry（record_id 判重，D5 ②）。"""
        rel = f"{topic}/index.json"
        idx = load_json(self.root, rel)
        if idx is None:
            return
        target_path = self._topic_target_path(topic, record_id)
        entry = {
            "target": _ref(target_path, record_id),
            "kind": kind,
            "title": title,
            "summary": f"{title}（第{chapter_order}章起）",
            "chapter_ranges": [{"start": chapter_order, "end": chapter_order}],
            "entity_refs": [_ref(target_path, record_id)],
            "tags": [tag],
            "safe_through": chapter_order,
        }
        existing = {e["target"]["record_id"] for e in idx.get("entries", [])}
        if record_id not in existing:
            idx.setdefault("entries", []).append(entry)
        idx["revision"] = idx.get("revision", 1) + 1
        idx["safe_through"] = max(idx.get("safe_through", 0), chapter_order)
        scope = idx.get("scope", {"chapter_ranges": [], "subject_refs": []})
        scope["chapter_ranges"] = self._merge_ranges(scope.get("chapter_ranges", []), chapter_order)
        idx["scope"] = scope
        self._write_json(rel, idx)

    @staticmethod
    def _merge_ranges(ranges: list, chapter_order: int) -> list:
        if not ranges:
            return [{"start": chapter_order, "end": chapter_order}]
        merged = [dict(r) for r in ranges]
        merged.append({"start": chapter_order, "end": chapter_order})
        merged.sort(key=lambda r: r["start"])
        out = []
        for r in merged:
            if out and r["start"] <= out[-1]["end"] + 1:
                out[-1]["end"] = max(out[-1]["end"], r["end"])
            else:
                out.append(r)
        return out

    # ==================== 章级落库 ====================
    def write_chapter(self, chapter_order: int, extraction: dict) -> list[str]:
        """把 ChapterExtraction 落库为 events/plot/characters/relationships/settings/threads。

        返回本次分配的 allocated_ids（供节点写入 ledger）。
        """
        self._local_to_real = {}
        self._name_to_ref = {}
        self._allocated_ids = []
        stage = self._stage_of(chapter_order)
        stage_id = stage["id"]
        self._current_block_id = self._block_id_for_stage(stage_id)

        new_claims = extraction.get("new_claims", [])
        new_events = extraction.get("new_events", [])
        claim_ids = self._allocate("claim", len(new_claims)) if new_claims else []
        ev_ids = self._allocate("ev", len(new_events)) if new_events else []
        update_ids = self._allocate("update", len(new_events)) if new_events else []

        for c, cid in zip(new_claims, claim_ids):
            self._local_to_real[c.get("local_id")] = cid
        for e, eid in zip(new_events, ev_ids):
            self._local_to_real[e.get("local_id")] = eid

        # 先解析所有新人物候选，建立 name -> ref
        for cand in extraction.get("new_character_candidates", []):
            name = cand.get("candidate_name") or cand.get("label")
            if name:
                self._ensure_char_ref(name, cand.get("introduced_at", chapter_order))

        if new_events:
            self._write_events_block(stage_id, chapter_order, new_events, ev_ids, update_ids, claim_ids, new_claims)

        summary = extraction.get("chapter_summary_markdown")
        if summary:
            self._write_chapter_md(chapter_order, stage_id, summary)

        for cand in extraction.get("new_setting_candidates", []):
            self._write_setting(chapter_order, cand)

        for cand in extraction.get("relationship_candidates", []):
            self._write_relationship(chapter_order, stage_id, cand)

        for cand in extraction.get("thread_update_candidates", []):
            self._write_thread(chapter_order, cand)

        return list(self._allocated_ids)

    def _write_events_block(self, stage_id, chapter_order, new_events, ev_ids, update_ids, claim_ids, new_claims):
        block_id = self._block_id_for_stage(stage_id)
        rel = f"events/{block_id}.json"
        block = load_json(self.root, rel)
        if block is None:
            block = _filemeta(self.novel_id, block_id, "event_collection", chapter_order)
            block["events"] = []

        claim_by_local = {c["local_id"]: c for c in new_claims}
        # 跨事件去重（D5 ②）：同一 claim 只内联一次，后续改走 trigger_refs
        claimed_locals: set[str] = set()

        for e, ev_id, upd_id in zip(new_events, ev_ids, update_ids):
            upd = e.get("update", {})
            participants = []
            for p in upd.get("participants", []):
                ent = p.get("entity_ref_or_candidate", {})
                role = p.get("role", "unknown")
                ref = None
                if ent.get("candidate_name"):
                    ref = self._ensure_char_ref(ent["candidate_name"], chapter_order)
                elif ent.get("path") and ent.get("record_id"):
                    ref = _ref(ent["path"], ent["record_id"])
                if ref:
                    participants.append({"entity_ref": ref, "role": role})

            claims = []
            reused_claim_local_ids = []
            for lid in upd.get("new_claim_local_ids", []):
                c = claim_by_local.get(lid)
                if not c:
                    continue
                if lid in claimed_locals:
                    reused_claim_local_ids.append(lid)
                    continue
                claimed_locals.add(lid)
                claims.append(self._to_claim(c, self._local_to_real.get(lid, "")))

            event_update = {
                "id": upd_id,
                "chapter_ranges": upd.get("chapter_ranges") or [{"start": chapter_order, "end": chapter_order}],
                "revealed_at": upd.get("revealed_at", chapter_order),
                "status": upd.get("status", "ongoing"),
                "story_time": upd.get("story_time"),
                "summary": upd.get("summary", ""),
                "participants": participants,
                "claims": claims,
                "trigger_refs": self._local_ids_to_refs(
                    (upd.get("trigger_claim_local_ids", []) or []) + reused_claim_local_ids
                ),
                "action_refs": self._local_ids_to_refs(upd.get("action_claim_local_ids", [])),
                "outcome_refs": self._local_ids_to_refs(upd.get("outcome_claim_local_ids", [])),
                "related_event_refs": [],
            }
            block["events"].append({
                "id": ev_id,
                "kind": "event",
                "title": e.get("title", ""),
                "introduced_at": e.get("introduced_at", chapter_order),
                "safe_through": chapter_order,
                "updates": [event_update],
            })

        block["revision"] = block.get("revision", 1) + 1
        block["safe_through"] = max(block.get("safe_through", 0), chapter_order)
        self._write_json(rel, block)
        self._append_root_entry("events", block_id, "event_collection", f"{stage_id} 事件块", chapter_order, "event")

    def _to_claim(self, c: dict, claim_id: str) -> dict:
        attributed = c.get("attributed_to_candidate_or_ref")
        attributed_ref = None
        if attributed:
            if attributed.get("candidate_name"):
                attributed_ref = self._resolve_name_ref(attributed["candidate_name"])
            elif attributed.get("path") and attributed.get("record_id"):
                attributed_ref = _ref(attributed["path"], attributed["record_id"])
        return {
            "id": claim_id,
            "text": c.get("text", ""),
            "certainty": c.get("certainty", "explicit"),
            "attributed_to_ref": attributed_ref,
            "revealed_at": c.get("revealed_at", 1),
            "source_refs": c.get("source_refs", []),
            "basis_refs": c.get("basis_refs", []),
            "supersedes_refs": c.get("supersedes_refs", []),
        }

    def _write_chapter_md(self, chapter_order: int, stage_id: str, summary: dict) -> None:
        info = self._chapter_index_for().get(chapter_order, {})
        chapter_id = info.get("chapter_id", f"ch-{chapter_order:06d}")
        fm = summary.get("front_matter", {})
        title = summary.get("title") or f"第{chapter_order}章"

        subject_refs = []
        for s in fm.get("subject_refs_or_candidates", []):
            if s.get("candidate_name"):
                ref = self._resolve_name_ref(s["candidate_name"])
                if ref:
                    subject_refs.append(ref)
            elif s.get("path"):
                subject_refs.append(_ref(s["path"], s.get("record_id")))

        record_refs = []
        for rid in fm.get("record_refs_or_local_ids", []):
            real = self._local_to_real.get(rid)
            if real:
                record_refs.append(_ref(f"events/{self._current_block_id}.json", real))

        lines = [
            "---",
            'schema_version: "2.0"',
            f"novel_id: {self.novel_id}",
            f"id: doc-{chapter_id}",
            "kind: chapter_summary",
            "revision: 1",
            f"safe_through: {chapter_order}",
            f"title: {title}",
            "chapter_ranges:",
            f"  - start: {chapter_order}",
            f"    end: {chapter_order}",
            f"as_of: {chapter_order}",
            "stage_ref:",
            "  path: navigation/stage-plan.json",
            f"  record_id: {stage_id}",
            "subject_refs:",
        ]
        for r in subject_refs:
            lines.append(f'  - path: {r["path"]}')
            lines.append(f'    record_id: {r["record_id"]}')
        lines.append("record_refs:")
        for r in record_refs:
            lines.append(f'  - path: {r["path"]}')
            lines.append(f'    record_id: {r["record_id"]}')
        lines.append("source_refs:")
        lines.append(f'  - path: {info.get("path", "")}')
        lines.append(f'    chapter_id: {chapter_id}')
        lines.append(f"    chapter_order: {chapter_order}")
        lines.append("---")
        lines.append("")
        lines.append(f"# {title}")
        lines.append("")
        lines.append(summary.get("body_markdown", ""))

        self._write_markdown(f"plot/chapters/{chapter_id}.md", "\n".join(lines))

    def _write_setting(self, chapter_order: int, cand: dict) -> None:
        label = cand.get("candidate_label") or cand.get("label", "")
        if not label:
            return
        sid = self._allocate("setting", 1)[0]
        category = cand.get("category", "other")
        if category not in _SETTING_CATEGORIES:
            category = "other"
        evidence_refs = self._local_ids_to_refs(cand.get("supporting_claim_local_ids", []) or cand.get("evidence_claim_local_ids", []))
        doc = _filemeta(self.novel_id, sid, "setting", chapter_order) | {
            "label": label,
            "category": category,
            "introduced_at": cand.get("introduced_at", chapter_order),
            "updates": [{
                "id": f"update-{sid}-001",
                "revealed_at": chapter_order,
                "chapter_ranges": [{"start": chapter_order, "end": chapter_order}],
                "claims": [],
                "definition_refs": [],
                "condition_refs": evidence_refs,
                "limitation_refs": [],
                "cost_refs": [],
                "exception_refs": [],
                "change_refs": [],
                "demonstration_event_refs": [],
                "related_event_refs": [],
                "links": [],
            }],
        }
        self._write_json(f"settings/entries/{sid}.json", doc)
        self._append_root_entry("settings", sid, "setting", label, chapter_order, "setting")

    def _write_relationship(self, chapter_order: int, stage_id: str, cand: dict) -> None:
        a = cand.get("subject_a_candidate_or_ref") or cand.get("subject_a", {})
        b = cand.get("subject_b_candidate_or_ref") or cand.get("subject_b", {})
        a_name = a.get("candidate_name")
        b_name = b.get("candidate_name")
        if not a_name or not b_name:
            return
        ref_a = self._ensure_char_ref(a_name, chapter_order)
        ref_b = self._ensure_char_ref(b_name, chapter_order)
        subjects = sorted([ref_a, ref_b], key=lambda r: r["record_id"])
        if subjects[0]["record_id"] == subjects[1]["record_id"]:
            return

        pair_key = (subjects[0]["record_id"], subjects[1]["record_id"])
        if pair_key in self._pair_rel_map:
            return
        rid = self._allocate("rel", 1)[0]
        self._pair_rel_map[pair_key] = rid
        facet = cand.get("facet", {})
        basis_refs = self._local_ids_to_refs(cand.get("basis_claim_local_ids", []) or cand.get("source_claim_local_ids", []))
        summary = facet.get("description", "") or cand.get("summary", "")
        doc = _filemeta(self.novel_id, rid, "relationship", chapter_order) | {
            "introduced_at": chapter_order,
            "subjects": subjects,
            "stages": [{
                "id": f"{rid}-stage-001",
                "stage_ref": _ref("navigation/stage-plan.json", stage_id),
                "chapter_ranges": [{"start": chapter_order, "end": chapter_order}],
                "as_of": chapter_order,
                "revealed_at": chapter_order,
                "summary": summary,
                "claims": [],
                "facets": [{
                    "type": facet.get("type", "other"),
                    "direction": facet.get("direction", "symmetric"),
                    "from_ref": None,
                    "to_ref": None,
                    "description": summary,
                    "basis_refs": basis_refs,
                }],
                "attitudes": [],
                "turning_event_refs": [],
            }],
        }
        self._write_json(f"relationships/pairs/{rid}.json", doc)
        self._append_root_entry("relationships", rid, "relationship", f"{a_name}×{b_name}", chapter_order, "relationship")
        for ref in subjects:
            self._write_by_character_index(ref, rid, f"{a_name}×{b_name}", chapter_order)

    def _write_by_character_index(self, subject_ref: dict, rel_id: str, title: str, chapter_order: int) -> None:
        char_id = subject_ref["record_id"]
        rel = f"relationships/by-character/{char_id}.json"
        idx = load_json(self.root, rel)
        if idx is None:
            idx = _filemeta(self.novel_id, f"idx-rel-{char_id}", "index", chapter_order) | {
                "title": f"{char_id} 关系入口",
                "scope": {"chapter_ranges": [], "subject_refs": [subject_ref]},
                "coverage_status": "partial",
                "entries": [],
            }
        entry = {
            "target": _ref(f"relationships/pairs/{rel_id}.json", rel_id),
            "kind": "relationship",
            "title": title,
            "summary": f"与{title}的关系",
            "chapter_ranges": [{"start": chapter_order, "end": chapter_order}],
            "entity_refs": [subject_ref],
            "tags": ["relationship"],
            "safe_through": chapter_order,
        }
        existing = {e["target"]["record_id"] for e in idx.get("entries", [])}
        if rel_id not in existing:
            idx.setdefault("entries", []).append(entry)
        idx["revision"] = idx.get("revision", 1) + 1
        idx["safe_through"] = max(idx.get("safe_through", 0), chapter_order)
        scope = idx.get("scope", {"chapter_ranges": [], "subject_refs": [subject_ref]})
        scope["chapter_ranges"] = self._merge_ranges(scope.get("chapter_ranges", []), chapter_order)
        idx["scope"] = scope
        self._write_json(rel, idx)

    def _write_thread(self, chapter_order: int, cand: dict) -> None:
        title = cand.get("title") or cand.get("label", "")
        if not title:
            return
        tid = self._allocate("thread", 1)[0]
        category = cand.get("category", "subplot")
        status = cand.get("status", "open")
        role = cand.get("role", "introduction")
        claim_refs = self._local_ids_to_refs(cand.get("source_claim_local_ids", []))
        doc = _filemeta(self.novel_id, tid, "story_thread", chapter_order) | {
            "label": title,
            "introduced_at": chapter_order,
            "updates": [{
                "id": f"update-{tid}-001",
                "revealed_at": chapter_order,
                "chapter_ranges": [{"start": chapter_order, "end": chapter_order}],
                "category": category,
                "status": status,
                "role": role,
                "summary": cand.get("summary", ""),
                "claims": [],
                "claim_refs": claim_refs,
                "event_refs": [],
                "resolution_refs": [],
            }],
        }
        self._write_json(f"threads/{tid}.json", doc)
        self._append_root_entry("threads", tid, "story_thread", title, chapter_order, "thread")

    # ==================== stage 聚合落库 ====================
    def write_stage_commit(self, stage: dict, payload: dict) -> None:
        stage_id = stage["id"]
        ranges = stage.get("chapter_ranges", [{"start": 1, "end": 1}])
        stage_start = ranges[0]["start"]
        stage_end = ranges[-1]["end"]
        as_of = payload.get("as_of") or stage_end

        arc = payload.get("arc_summary")
        if arc:
            self._write_arc_md(stage_id, stage_start, stage_end, as_of, arc)

        for cs in payload.get("character_stages", []):
            self._write_entity_stage_md("characters", cs, stage_id, stage_start, stage_end, as_of, "character_stage")

        for fs in payload.get("faction_stages", []):
            self._write_entity_stage_md("factions", fs, stage_id, stage_start, stage_end, as_of, "faction_stage")

        for rs in payload.get("relationship_snapshots", []):
            self._append_relationship_snapshot(stage_id, stage_start, stage_end, as_of, rs)

        for es in payload.get("emotional_stages", []):
            self._write_emotional(stage_id, stage_start, stage_end, as_of, es)

    def _write_arc_md(self, stage_id, stage_start, stage_end, as_of, arc: dict) -> None:
        fm = arc.get("front_matter", {}) if isinstance(arc.get("front_matter"), dict) else {}
        title = fm.get("title") or f"{stage_id} 阶段"
        order = self._stage_order.get(stage_id, 1)
        arc_id = f"arc-{order:03d}"
        lines = [
            "---",
            'schema_version: "2.0"',
            f"novel_id: {self.novel_id}",
            f"id: doc-{arc_id}",
            "kind: arc_summary",
            "revision: 1",
            f"safe_through: {as_of}",
            f"title: {title}",
            "chapter_ranges:",
            f"  - start: {stage_start}",
            f"    end: {stage_end}",
            f"as_of: {as_of}",
            "stage_ref:",
            "  path: navigation/stage-plan.json",
            f"  record_id: {stage_id}",
            "subject_refs: []",
            "record_refs: []",
            "source_refs: []",
            "---",
            "",
            f"# {title}",
            "",
            arc.get("body_markdown", ""),
        ]
        self._write_markdown(f"plot/arcs/{arc_id}.md", "\n".join(lines))
        self._append_root_entry("plot", f"doc-{arc_id}", "arc_summary", title, as_of, "plot")

    def _write_entity_stage_md(self, topic, cs: dict, stage_id, stage_start, stage_end, as_of, kind) -> None:
        # 优先用 candidate_name 通过名字索引解析真实实体 ID（Agent 的 entity_ref 是猜测 ID，不可信）
        ent_id = None
        label = None
        cand_name = cs.get("candidate_name")
        if cand_name:
            ref = self._resolve_name_ref(cand_name)
            if ref:
                ent_id = ref["record_id"]
                label = cand_name
        if not ent_id:
            ent_ref = cs.get("entity_ref") or {}
            ent_id = ent_ref.get("record_id")
            label = ent_id
        if not ent_id:
            return
        sm = cs.get("stage_markdown", {}) or {}
        sm_fm = sm.get("front_matter", {}) if isinstance(sm.get("front_matter"), dict) else {}
        title = sm_fm.get("title") or f"{stage_id} 阶段"
        order = self._stage_order.get(stage_id, 1)
        doc_id = f"doc-{ent_id}-stage-{order:03d}"
        lines = [
            "---",
            'schema_version: "2.0"',
            f"novel_id: {self.novel_id}",
            f"id: {doc_id}",
            f"kind: {kind}",
            "revision: 1",
            f"safe_through: {as_of}",
            f"title: {title}",
            "chapter_ranges:",
            f"  - start: {stage_start}",
            f"    end: {stage_end}",
            f"as_of: {as_of}",
            "stage_ref:",
            "  path: navigation/stage-plan.json",
            f"  record_id: {stage_id}",
            "subject_refs:",
            f"  - path: {topic}/{ent_id}/index.json",
            f"    record_id: {ent_id}",
            "record_refs: []",
            "source_refs: []",
            "---",
            "",
            f"# {title}",
            "",
            sm.get("body_markdown", ""),
        ]
        self._write_markdown(f"{topic}/{ent_id}/stages/stage-{order:03d}.md", "\n".join(lines))
        self._append_entity_stage_entry(topic, ent_id, doc_id, order, kind, title, stage_start, stage_end, as_of)
        # 更新实体 current_summary
        self._patch_entity_current_summary(topic, ent_id, cs.get("current_summary_update", ""), as_of)

    def _append_entity_stage_entry(self, topic, ent_id, doc_id, stage_no, kind, title, stage_start, stage_end, as_of) -> None:
        rel = f"{topic}/{ent_id}/index.json"
        doc = load_json(self.root, rel)
        if doc is None:
            return
        entry = {
            "target": _ref(f"{topic}/{ent_id}/stages/stage-{stage_no:03d}.md", doc_id),
            "kind": kind,
            "title": title,
            "summary": f"{title}（第{stage_start}—{stage_end}章）",
            "chapter_ranges": [{"start": stage_start, "end": stage_end}],
            "entity_refs": [_ref(f"{topic}/{ent_id}/index.json", ent_id)],
            "tags": [kind.split("_")[0]],
            "safe_through": as_of,
        }
        existing = {e["target"]["record_id"] for e in doc.get("entries", [])}
        if doc_id not in existing:
            doc.setdefault("entries", []).append(entry)
        doc["revision"] = doc.get("revision", 1) + 1
        doc["safe_through"] = max(doc.get("safe_through", 0), as_of)
        self._write_json(rel, doc)

    def _patch_entity_current_summary(self, topic, ent_id, summary: str, as_of: int) -> None:
        if not summary:
            return
        rel = f"{topic}/{ent_id}/index.json"
        doc = load_json(self.root, rel)
        if doc is None:
            return
        current = doc.get("current", {})
        if not isinstance(current, dict):
            current = {}
        current["current_summary"] = summary
        doc["current"] = current
        doc["revision"] = doc.get("revision", 1) + 1
        doc["safe_through"] = max(doc.get("safe_through", 0), as_of)
        self._write_json(rel, doc)

    def _append_relationship_snapshot(self, stage_id, stage_start, stage_end, as_of, rs: dict) -> None:
        # 兼容 04-prompt §2.2：snapshot 嵌套在 rs["snapshot"]；subjects 在 rs["subjects"]
        snapshot = rs.get("snapshot", rs)
        rel_info = rs.get("relationship_ref_or_new", {})
        subjects = rs.get("subjects", [])
        # 从 subjects（Ref 列表）解析真实 char refs
        refs = []
        for s in subjects:
            if s.get("candidate_name"):
                ref = self._resolve_name_ref(s["candidate_name"])
                if ref:
                    refs.append(ref)
            elif s.get("path") and s.get("record_id"):
                refs.append(_ref(s["path"], s["record_id"]))
        # 兜底：new_rel.pair_names（demo 格式）
        if len(refs) < 2:
            new_rel = rel_info.get("new_rel", {})
            for name in new_rel.get("pair_names", []):
                ref = self._resolve_name_ref(name)
                if ref:
                    refs.append(ref)
        if len(refs) < 2:
            return
        subjects_sorted = sorted(refs, key=lambda r: r["record_id"])
        pair_key = (subjects_sorted[0]["record_id"], subjects_sorted[1]["record_id"])

        rel_id = self._pair_rel_map.get(pair_key)
        if rel_id is None:
            rel_id = self._allocate("rel", 1)[0]
            self._pair_rel_map[pair_key] = rel_id
            label_a = subjects_sorted[0]["record_id"]
            label_b = subjects_sorted[1]["record_id"]
            doc = _filemeta(self.novel_id, rel_id, "relationship", as_of) | {
                "introduced_at": stage_start,
                "subjects": subjects_sorted,
                "stages": [],
            }
            self._write_json(f"relationships/pairs/{rel_id}.json", doc)
            self._append_root_entry("relationships", rel_id, "relationship", f"{label_a}×{label_b}", as_of, "relationship")
            for ref in subjects_sorted:
                self._write_by_character_index(ref, rel_id, f"{label_a}×{label_b}", as_of)
        else:
            doc = load_json(self.root, f"relationships/pairs/{rel_id}.json")
            if doc is None:
                return

        order = self._stage_order.get(stage_id, 1)
        snap_id = f"{rel_id}-stage-{order:03d}"
        new_stage = {
            "id": snap_id,
            "stage_ref": _ref("navigation/stage-plan.json", stage_id),
            "chapter_ranges": [{"start": stage_start, "end": stage_end}],
            "as_of": as_of,
            "revealed_at": snapshot.get("revealed_at", as_of),
            "summary": snapshot.get("summary", ""),
            "claims": snapshot.get("claims", []),
            "facets": snapshot.get("facets", []),
            "attitudes": snapshot.get("attitudes", []),
            "turning_event_refs": snapshot.get("turning_event_refs", []),
        }
        existing_ids = {s["id"] for s in doc.get("stages", [])}
        if snap_id not in existing_ids:
            doc.setdefault("stages", []).append(new_stage)
        doc["revision"] = doc.get("revision", 1) + 1
        doc["safe_through"] = max(doc.get("safe_through", 0), as_of)
        self._write_json(f"relationships/pairs/{rel_id}.json", doc)

    def _write_emotional(self, stage_id, stage_start, stage_end, as_of, es: dict) -> None:
        emo_info = es.get("emotional_ref_or_new", {})
        # 兼容：已有 ref 复用，否则新建
        existing_ref = emo_info.get("existing_ref", {})
        if existing_ref.get("record_id"):
            emo_id = existing_ref["record_id"]
            emo_doc = load_json(self.root, f"emotions/{emo_id}/index.json")
            if emo_doc is None:
                emo_id = self._allocate("emo", 1)[0]
                emo_doc = _filemeta(self.novel_id, emo_id, "emotional_index", as_of) | {
                    "label": "", "introduced_at": stage_start, "participants": [], "assessments": [], "entries": [],
                }
        else:
            emo_id = self._allocate("emo", 1)[0]
            emo_doc = _filemeta(self.novel_id, emo_id, "emotional_index", as_of) | {
                "label": "", "introduced_at": stage_start, "participants": [], "assessments": [], "entries": [],
            }

        sm = es.get("stage_markdown", {}) or {}
        sm_fm = sm.get("front_matter", {}) if isinstance(sm.get("front_matter"), dict) else {}
        title = sm_fm.get("title") or f"{stage_id} 感情分析"
        order = self._stage_order.get(stage_id, 1)
        doc_id = f"doc-{emo_id}-stage-{order:03d}"

        assessment = es.get("new_assessment", {})
        if assessment:
            assess_id = f"assessment-{emo_id}-{order:03d}"
            existing_aids = {a["id"] for a in emo_doc.get("assessments", [])}
            if assess_id not in existing_aids:
                emo_doc.setdefault("assessments", []).append({
                    "id": assess_id,
                    "revealed_at": assessment.get("revealed_at", as_of),
                    "category": assessment.get("category", "uncertain"),
                    "status": assessment.get("status", "uncertain"),
                    "relationship_links": assessment.get("relationship_links", []),
                })

        entry = {
            "target": _ref(f"emotions/{emo_id}/stages/stage-{order:03d}.md", doc_id),
            "kind": "emotional_stage",
            "title": title,
            "summary": f"{title}（第{stage_start}—{stage_end}章）",
            "chapter_ranges": [{"start": stage_start, "end": stage_end}],
            "entity_refs": [],
            "tags": ["emotion"],
            "safe_through": as_of,
        }
        existing_docids = {e["target"]["record_id"] for e in emo_doc.get("entries", [])}
        if doc_id not in existing_docids:
            emo_doc.setdefault("entries", []).append(entry)
        emo_doc["revision"] = emo_doc.get("revision", 1) + 1
        emo_doc["safe_through"] = max(emo_doc.get("safe_through", 0), as_of)
        self._write_json(f"emotions/{emo_id}/index.json", emo_doc)
        self._append_root_entry("emotions", emo_id, "emotional_index", title, as_of, "emotion")

        lines = [
            "---",
            'schema_version: "2.0"',
            f"novel_id: {self.novel_id}",
            f"id: {doc_id}",
            "kind: emotional_stage",
            "revision: 1",
            f"safe_through: {as_of}",
            f"title: {title}",
            "chapter_ranges:",
            f"  - start: {stage_start}",
            f"    end: {stage_end}",
            f"as_of: {as_of}",
            "stage_ref:",
            "  path: navigation/stage-plan.json",
            f"  record_id: {stage_id}",
            "subject_refs: []",
            "record_refs: []",
            "source_refs: []",
            "---",
            "",
            f"# {title}",
            "",
            sm.get("body_markdown", ""),
        ]
        self._write_markdown(f"emotions/{emo_id}/stages/stage-{order:03d}.md", "\n".join(lines))
