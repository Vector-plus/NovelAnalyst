"""B 类 · 实体解析工具（ChapterReActAgent / StageCommitReActAgent 用）。

对应 03 文档 §5.3：``resolve_name`` / ``fetch_entity_current`` / ``lookup_stage``。

- resolve_name 锚定 name_catalog（navigation/names/ 分片），精确匹配（match_mode=exact），
  返回候选列表不假设唯一实体（templates §4.4 / §4.5）。
- 工具均为纯读磁盘、无状态：deepread 过程中索引持续增长，每次调用读最新落盘文件，
  天然与 IndexWriter（P2c）同步，不依赖内存缓存。
- 工具 description 为静态字符串（R2：禁止动态内容），变量只进 User prompt。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool

from deerflow_simple.index_builder.services.name_index import normalize_name
from deerflow_simple.index_builder.tools.common import load_json, parse_ref_path

_STAGE_PLAN_PATH = "navigation/stage-plan.json"
_NAME_CATALOG_PATH = "navigation/names/index.json"


def _resolve_name_candidates(novel_root: str, name: str) -> list[dict]:
    """精确匹配规范化名字，返回候选 matches 列表（读 name_catalog 分片）。"""
    root = Path(novel_root)
    key = normalize_name(name)
    if not key:
        return []
    catalog = load_json(root, _NAME_CATALOG_PATH)
    if not catalog:
        return []
    hits: list[dict] = []
    for shard in catalog.get("shard_refs", []):
        path = shard.get("path")
        if not path:
            continue
        part = load_json(root, path)
        if not part:
            continue
        for entry in part.get("entries", []):
            if normalize_name(entry.get("normalized_name", "")) == key:
                hits.extend(entry.get("matches", []))
    return hits


def build_entity_tools(novel_root: str) -> list:
    root = Path(novel_root)

    @tool
    def resolve_name(name: str, context_hint: Optional[str] = None) -> str:
        """将人物/势力名字解析为已有实体候选 Ref 列表（精确匹配，不做模糊）。

        参数:
            name: 名字（如 '张小凡'）。
            context_hint: 可选上下文线索（如出场章节/身份），帮助消歧。

        返回:
            JSON 字符串：{"status": "unique"/"multiple"/"no_match", "refs": [...]}
        """
        matches = _resolve_name_candidates(novel_root, name)
        if not matches:
            return json.dumps({"status": "no_match", "refs": []}, ensure_ascii=False)
        refs = [m.get("entity_ref") for m in matches if m.get("entity_ref")]
        if len(refs) == 1:
            return json.dumps({"status": "unique", "refs": refs}, ensure_ascii=False)
        return json.dumps({"status": "multiple", "refs": refs}, ensure_ascii=False)

    @tool
    def fetch_entity_current(entity_ref: str) -> str:
        """读取实体 index.json 的 current 摘要（label、current_summary、identity_notes）。

        参数:
            entity_ref: 实体引用，形如 'characters/char-0001/index.json' 或
                JSON 字符串 {"path":..., "record_id":...}。

        返回:
            实体 current 片段原始 JSON。
        """
        path = parse_ref_path(entity_ref)
        data = load_json(root, path) if path else None
        if data is None:
            return f"实体不存在: {entity_ref}"
        current = data.get("current", data)
        return json.dumps(current, ensure_ascii=False)

    @tool
    def lookup_stage(chapter_order: int) -> str:
        """查询某章落在哪个 stage（阶段骨架 navigation/stage-plan.json）。

        参数:
            chapter_order: 章节号（1 起）。

        返回:
            JSON 字符串：该章所属 stage 的 id、title、chapter_ranges。
        """
        sp = load_json(root, _STAGE_PLAN_PATH)
        if not sp:
            return json.dumps(
                {"status": "no_stage", "chapter_order": chapter_order},
                ensure_ascii=False,
            )
        for st in sp.get("stages", []):
            for r in st.get("chapter_ranges", []):
                if r.get("start", 0) <= chapter_order <= r.get("end", 0):
                    return json.dumps(
                        {
                            "status": "ok",
                            "stage_id": st.get("id"),
                            "title": st.get("title"),
                            "chapter_ranges": st.get("chapter_ranges"),
                        },
                        ensure_ascii=False,
                    )
        return json.dumps(
            {"status": "no_stage", "chapter_order": chapter_order},
            ensure_ascii=False,
        )

    return [resolve_name, fetch_entity_current, lookup_stage]
