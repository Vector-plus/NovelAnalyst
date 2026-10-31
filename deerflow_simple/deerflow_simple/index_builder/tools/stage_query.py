"""E 类 · 查询辅助工具（StageCommitReActAgent 用）。

对应 03 文档 §5.6：``fetch_event_detail`` / ``fetch_related_claims`` /
``list_entity_stages`` / ``fetch_entity_summary``。

纯读磁盘、无状态（同 entity.py 约定）。fetch_related_claims 一期留桩（同 C 类去重，
需遍历 events 块做主体归属查询，二期补）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool

from deerflow_simple.index_builder.tools.common import load_json, parse_ref_path


def _record_id_of(event_ref) -> str | None:
    """从 event_ref（dict / str / JSON 字符串）解析 record_id。"""
    if isinstance(event_ref, dict):
        return event_ref.get("record_id")
    if isinstance(event_ref, str):
        s = event_ref.strip()
        if s.startswith("{"):
            try:
                return json.loads(s).get("record_id")
            except (json.JSONDecodeError, ValueError):
                return None
    return None


def build_stage_query_tools(novel_root: str) -> list:
    root = Path(novel_root)

    @tool
    def fetch_entity_summary(entity_ref: str) -> str:
        """读取实体最新的 current_summary 摘要。

        参数:
            entity_ref: 实体引用。

        返回:
            JSON 字符串：{"label": ..., "current_summary": ...}
        """
        path = parse_ref_path(entity_ref)
        data = load_json(root, path) if path else None
        if data is None:
            return f"实体不存在: {entity_ref}"
        current = data.get("current", {})
        summary = current.get("current_summary") if isinstance(current, dict) else None
        return json.dumps(
            {"label": data.get("label", ""), "current_summary": summary or ""},
            ensure_ascii=False,
        )

    @tool
    def fetch_event_detail(event_ref: str) -> str:
        """读取事件的完整 updates 与 claims（按 record_id 精确定位）。

        参数:
            event_ref: 事件引用，形如 'events/block-0001.json' 或含 record_id 的
                JSON 字符串 {"path":..., "record_id":"ev-0001"}。

        返回:
            事件详情 JSON。
        """
        path = parse_ref_path(event_ref)
        if not path:
            return f"事件引用无效: {event_ref}"
        data = load_json(root, path)
        if data is None:
            return f"事件不存在: {event_ref}"
        record_id = _record_id_of(event_ref)
        if record_id:
            for ev in data.get("events", []):
                if ev.get("id") == record_id:
                    return json.dumps(ev, ensure_ascii=False)
            return f"事件 {record_id} 不在 {path} 中"
        return json.dumps(data, ensure_ascii=False)

    @tool
    def fetch_related_claims(subject_ref: str, chapter_range: Optional[str] = None) -> str:
        """读取与某主体相关的 claims（一期留桩，返回空）。

        参数:
            subject_ref: 主体引用。
            chapter_range: 可选章节范围。
        """
        return json.dumps({"claims": []}, ensure_ascii=False)

    @tool
    def list_entity_stages(entity_ref: str) -> str:
        """列出实体已有的 stage Markdown 文件（供新 stage 编号）。

        参数:
            entity_ref: 实体引用。

        返回:
            JSON 字符串：{"stages": [...]}
        """
        path = parse_ref_path(entity_ref)
        if not path:
            return json.dumps({"stages": []}, ensure_ascii=False)
        stages_dir = Path(path).parent / "stages"
        full = root / stages_dir
        stages = []
        if full.is_dir():
            stages = sorted(x.name for x in full.iterdir() if x.is_file())
        return json.dumps({"stages": stages}, ensure_ascii=False)

    return [
        fetch_entity_summary,
        fetch_event_detail,
        fetch_related_claims,
        list_entity_stages,
    ]
