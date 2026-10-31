"""名字消歧的确定性匹配层（search_name 的第 1、2 层）。

对应设计文档《03-核心图设计_解说词生成.md》§4 与《04-prompt_解说任务核查.md》：

- **第 1 层 · NFKC 精确匹配**：Unicode NFKC 归一后，比对 `normalized_name` 与所有
  `matches[].surface`，纯查表、零幻觉。
- **第 2 层 · 模糊匹配**：difflib 子串 + 相似度（threshold≈0.6），仍为确定性。
- **第 3 层 · LLM 语义召回**：仅前两层全 miss 才触发，在 `tools.py` 中实现（需 model）。

关键护栏：**「存在性」由代码裁决，LLM 只负责「挑」，不负责「回答存在吗」**。
本模块只做确定性匹配，绝不引入 LLM。
"""

from __future__ import annotations

import difflib
import json
import unicodedata

from deerflow_simple.narration.read_only import ReadOnlyFs

# difflib 相似度阈值（设计文档 §4 提到 threshold≈0.6；中文 2~4 字名在 0.85 下几乎全 miss）
_FUZZY_THRESHOLD = 0.6


def nfkc(s: str) -> str:
    """Unicode NFKC 归一 + 去首尾空白（索引模板 §4.4 约定 normalization=nfkc_trim）。"""
    return unicodedata.normalize("NFKC", s).strip()


def _load_json(fs: ReadOnlyFs, path: str) -> dict | list | None:
    """从 fs 读取 JSON；读不到（错误提示）或解析失败返回 None。"""
    text = fs.read_file(path)
    if text.startswith("("):
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def collect_name_surfaces(fs: ReadOnlyFs) -> list[dict]:
    """从 names 索引收集所有名字 surface。

    按 §4.4/§4.5：`navigation/names/index.json` 只列分片（`shard_refs`），
    每个 `part-*.json` 含 `entries[{normalized_name, matches[{surface, entity_ref, ...}]}]`。

    返回扁平化的名字列表，每条含 surface / normalized_name / entity_ref / entity_type。
    """
    index = _load_json(fs, "navigation/names/index.json")
    if not isinstance(index, dict):
        return []
    surfaces: list[dict] = []
    for shard in index.get("shard_refs", []) or []:
        if not isinstance(shard, dict):
            continue
        part = _load_json(fs, shard.get("path", ""))
        if not isinstance(part, dict):
            continue
        for entry in part.get("entries", []) or []:
            if not isinstance(entry, dict):
                continue
            normalized_name = entry.get("normalized_name", "")
            for m in entry.get("matches", []) or []:
                if not isinstance(m, dict):
                    continue
                surfaces.append(
                    {
                        "surface": m.get("surface", ""),
                        "normalized_name": normalized_name,
                        "entity_ref": m.get("entity_ref", {}),
                        "entity_type": m.get("entity_type", ""),
                        "name_type": m.get("name_type", ""),
                    }
                )
    return surfaces


def _dedupe_by_entity(candidates: list[dict]) -> list[dict]:
    """按 entity_ref.record_id 去重（同名多 surface 归并为一个实体）。"""
    seen: set[str] = set()
    result: list[dict] = []
    for c in candidates:
        key = (c.get("entity_ref") or {}).get("record_id") or c.get("surface")
        if key not in seen:
            seen.add(key)
            result.append(c)
    return result


def resolve_name_exact(fs: ReadOnlyFs, name: str) -> list[dict]:
    """第 1 层：NFKC 精确匹配。返回命中的实体候选列表（去重后）。

    命中 0 个 → 空列表；1 个 → unique；≥2 个 → ambiguous（由上层裁决）。
    """
    target = nfkc(name)
    if not target:
        return []
    hits = []
    for s in collect_name_surfaces(fs):
        if nfkc(s["surface"]) == target or nfkc(s["normalized_name"]) == target:
            hits.append(s)
    return _dedupe_by_entity(hits)


def resolve_name_fuzzy(fs: ReadOnlyFs, name: str, threshold: float = _FUZZY_THRESHOLD) -> list[dict]:
    """第 2 层：模糊匹配（difflib 子串 + 相似度）。

    返回带 `score` 的候选列表，按相似度降序；子串命中优先于纯相似度命中。
    """
    target = nfkc(name)
    if not target:
        return []
    candidates: list[dict] = []
    seen_surfaces: set[str] = set()
    for s in collect_name_surfaces(fs):
        surface_norm = nfkc(s["surface"])
        if not surface_norm:
            continue
        if surface_norm in seen_surfaces:
            continue
        seen_surfaces.add(surface_norm)
        ratio = difflib.SequenceMatcher(None, target, surface_norm).ratio()
        is_substr = target in surface_norm or surface_norm in target
        if is_substr or ratio >= threshold:
            candidates.append({**s, "score": ratio, "is_substr": is_substr})
    candidates.sort(key=lambda c: (-int(c["is_substr"]), -c["score"]))
    return _dedupe_by_entity(candidates)
