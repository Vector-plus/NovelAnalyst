"""NameIndex —— 名字归一 + 查找（锚定 navigation/names/ name_catalog）。

纠正 demo index_writer.py 的 NameIndex：demo 从 ``characters/index.json`` 反推
name→char_id 映射，但 skeleton 已初始化 ``navigation/names/index.json``
（name_catalog）+ 名字分片（name_lookup）作为名字归一与查找的**权威源**
（templates §4.4 / §4.5）。

职责：
- normalize(name)：Unicode NFKC 后去首尾空白（templates §4.4 normalization）。
- resolve(name)：精确匹配（match_mode=exact），返回候选 matches 数组，不假设
  唯一实体（templates §4.5「matches 是候选数组」）。
- register(...)：deepread 建实体时登记名字（确定性写入 name_lookup 分片）。

一期简化：名字统一写入第一个分片 ``navigation/names/part-0001.json``（首版允许
读取程序在分片中精确查找，templates §4.4）；按首字/容量拆分留待二期。
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

from deerflow_simple.index_builder.services.fingerprint import json_bytes

_NAMES_INDEX_PATH = "navigation/names/index.json"
_FIRST_PART_ID = "names-part-0001"
_FIRST_PART_PATH = "navigation/names/part-0001.json"


def normalize_name(name: str) -> str:
    """Unicode NFKC 后去首尾空白（templates §4.4 normalization）。"""
    return unicodedata.normalize("NFKC", (name or "").strip())


class NameIndex:
    """名字 → 实体候选映射（内存索引 + 落盘 name_lookup 分片）。"""

    def __init__(self, novel_root: str, novel_id: str):
        self.root = Path(novel_root)
        self.novel_id = novel_id
        # normalized_name -> list[matches]
        self._lookup: dict[str, list[dict]] = {}
        self._load_existing()

    # ------------------------------------------------------------------
    # 加载 / 落盘
    # ------------------------------------------------------------------
    def _load_existing(self) -> None:
        """从所有 name_lookup 分片恢复 normalized_name -> matches 映射。"""
        catalog_path = self.root / _NAMES_INDEX_PATH
        if not catalog_path.exists():
            return
        try:
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        for shard in catalog.get("shard_refs", []):
            path = shard.get("path")
            if not path:
                continue
            full = self.root / path
            if not full.exists():
                continue
            try:
                data = json.loads(full.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            for entry in data.get("entries", []):
                key = normalize_name(entry.get("normalized_name", ""))
                if key:
                    self._lookup[key] = entry.get("matches", [])

    def _load_part(self) -> dict:
        full = self.root / _FIRST_PART_PATH
        if full.exists():
            try:
                data = json.loads(full.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except (json.JSONDecodeError, OSError):
                pass
        return {
            "schema_version": "2.0",
            "novel_id": self.novel_id,
            "id": _FIRST_PART_ID,
            "kind": "name_lookup",
            "revision": 1,
            "safe_through": 0,
            "entries": [],
        }

    def _save_part(self, part: dict) -> None:
        full = self.root / _FIRST_PART_PATH
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(json_bytes(part))

    def _ensure_catalog_ref(self) -> None:
        """确保 name_catalog 的 shard_refs 包含首个分片（幂等）。"""
        catalog_path = self.root / _NAMES_INDEX_PATH
        if not catalog_path.exists():
            return
        try:
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        refs = catalog.get("shard_refs", [])
        if _FIRST_PART_PATH not in {r.get("path") for r in refs}:
            refs.append({"path": _FIRST_PART_PATH, "record_id": _FIRST_PART_ID})
            catalog["shard_refs"] = refs
            catalog_path.write_bytes(json_bytes(catalog))

    # ------------------------------------------------------------------
    # 查询 / 登记
    # ------------------------------------------------------------------
    def resolve(self, name: str) -> list[dict]:
        """精确匹配规范化名字，返回候选 matches 数组（可能为空）。

        不做模糊匹配（templates §4.4：不认识的称呼返回未命中或候选）。
        """
        key = normalize_name(name)
        return list(self._lookup.get(key, []))

    def resolve_refs(self, name: str) -> list[dict]:
        """resolve 的便捷形态：只返回实体 Ref 列表（供 IndexWriter 用）。"""
        return [m.get("entity_ref") for m in self.resolve(name) if m.get("entity_ref")]

    def register(
        self,
        name: str,
        entity_ref: dict,
        *,
        entity_type: str = "character",
        name_type: str = "name",
        identity_status: str = "confirmed",
        revealed_at: int = 0,
        surface: str | None = None,
        aliases: list[str] | None = None,
    ) -> None:
        """登记一个名字（含主名 + 可选别名）到 name_lookup 首个分片。

        由 IndexWriter（确定性路径）调用，Agent 不直接调用。
        幂等（记录级 ②）：同一 normalized_name 下已存在 identical entity_ref 时
        跳过，避免重复 matches。
        """
        names = [name] + (aliases or [])
        part = self._load_part()
        changed = False
        for raw in names:
            key = normalize_name(raw)
            if not key:
                continue
            match = {
                "surface": surface or raw,
                "entity_ref": entity_ref,
                "entity_type": entity_type,
                "name_type": name_type,
                "identity_status": identity_status,
                "chapter_ranges": [],
                "revealed_at": revealed_at,
                "source_refs": [],
                "basis_refs": [],
            }
            existing = self._lookup.get(key, [])
            if any(m.get("entity_ref") == entity_ref for m in existing):
                continue
            self._lookup.setdefault(key, []).append(match)

            entry = next(
                (e for e in part.get("entries", [])
                 if normalize_name(e.get("normalized_name", "")) == key),
                None,
            )
            if entry is None:
                entry = {"normalized_name": key, "matches": []}
                part.setdefault("entries", []).append(entry)
            if not any(m.get("entity_ref") == entity_ref for m in entry.get("matches", [])):
                entry["matches"].append(match)
            changed = True

        if changed:
            part["revision"] = part.get("revision", 1) + 1
            self._save_part(part)
            self._ensure_catalog_ref()
