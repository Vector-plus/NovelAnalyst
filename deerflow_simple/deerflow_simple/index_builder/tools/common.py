"""工具公共辅助 —— Ref 解析 / JSON 读取 / 章节索引构建（deepread 工具共用）。

这些是纯确定性 helper，被 A/B/C/E 类工具复用，不对外暴露为 LangChain tool。
"""

from __future__ import annotations

import json
from pathlib import Path


def load_json(root: Path, rel_path: str | None) -> dict | None:
    """读取 novel_root 下的 JSON 文件，失败/不存在返回 None。"""
    if not rel_path:
        return None
    full = root / rel_path
    if not full.is_file():
        return None
    try:
        data = json.loads(full.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def parse_ref_path(entity_ref) -> str | None:
    """从 Ref（dict / str / JSON 字符串）解析出相对 novel_root 的文件路径。

    兼容三种形态：
    - dict：``{"path": "...", "record_id": "..."}``
    - str 路径：``"characters/char-0001/index.json"``
    - str JSON：``'{"path": "..."}'``
    """
    if entity_ref is None:
        return None
    if isinstance(entity_ref, dict):
        return entity_ref.get("path")
    if isinstance(entity_ref, str):
        s = entity_ref.strip()
        if s.startswith("{"):
            try:
                return json.loads(s).get("path")
            except (json.JSONDecodeError, ValueError):
                return None
        return s or None
    return None


def build_chapter_index(novel_root: str) -> dict:
    """构建 ``chapter_order -> {chapter_id, path, title, paragraph_count, vol_id}``。

    读 ``source/index.json``（卷清单）+ 各 ``source/vol-XXX/index.json``（章清单）。
    与 demo ``_build_chapter_index`` 一致，但改为显式参数 + 容错。
    """
    root = Path(novel_root)
    mapping: dict[int, dict] = {}
    source_index = load_json(root, "source/index.json")
    if not source_index:
        return mapping
    for entry in source_index.get("entries", []):
        vol_path = entry.get("target", {}).get("path", "")
        vol_id = vol_path.split("/")[1] if "/" in vol_path else ""
        vol_index = load_json(root, vol_path)
        if not vol_index:
            continue
        for ch in vol_index.get("chapters", []):
            order = ch.get("chapter_order")
            if order is None:
                continue
            mapping[order] = {
                "chapter_id": ch.get("id"),
                "path": ch.get("path"),
                "title": ch.get("title"),
                "paragraph_count": ch.get("paragraph_count", 0),
                "vol_id": vol_id,
            }
    return mapping


def total_chapters(novel_root: str) -> int:
    """从 source/index.json 读全书章节总数。"""
    root = Path(novel_root)
    source_index = load_json(root, "source/index.json")
    if not source_index:
        return 0
    ranges = source_index.get("scope", {}).get("chapter_ranges", [])
    return ranges[-1].get("end", 0) if ranges else 0
