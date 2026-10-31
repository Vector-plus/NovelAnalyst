"""12 名字索引补齐 —— 从 characters/index.json 生成 navigation/names/part-*.json。

背景：novel-index-creator 的精读工作流漏掉了「生成名字分片」这一步，导致真实索引的
`navigation/names/index.json` 的 `shard_refs` 为空，解说词的 `search_name` 无法按名字定位人物。

本脚本是方案 A（MVP 数据补齐）：只覆盖主名（`name_type=name`），不含别名/化名/称号，
从 `characters/index.json` 的 `title` 字段生成 `name_lookup` 分片，让 search_name 能命中主名。

关键约束：
- 仅主名：`surface = title`，`name_type = "name"`，`identity_status = "confirmed"`。
- `revealed_at` 取 `chapter_ranges[0].start`（首现章）。
- `basis_refs` 用实体 index 作为「名称↔实体」依据占位；`source_refs` 留空。
  真实原文锚点需后续精读工作流补全。

用法：
    python examples/12_backfill_names.py [novel_root]
    # 默认 novel_root = .deerflow_simple/workspace/55fa54e9abf04ed88da8b3abf9ba3993/novel
"""

import json
import sys
import unicodedata
from pathlib import Path

DEFAULT_NOVEL_ROOT = ".deerflow_simple/workspace/55fa54e9abf04ed88da8b3abf9ba3993/novel"


def nfkc(s: str) -> str:
    """Unicode NFKC 归一 + 去首尾空白（与 names.py 的 nfkc 一致）。"""
    return unicodedata.normalize("NFKC", s).strip()


def main() -> None:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(DEFAULT_NOVEL_ROOT)

    characters_index = root / "characters" / "index.json"
    if not characters_index.exists():
        print(f"找不到 characters/index.json: {characters_index}")
        sys.exit(1)

    data = json.loads(characters_index.read_text(encoding="utf-8"))
    novel_id = data.get("novel_id", "wukon")

    entries = []
    max_revealed = 0
    for item in data.get("entries", []) or []:
        target = item.get("target") or {}
        title = (item.get("title") or "").strip()
        record_id = target.get("record_id")
        path = target.get("path")
        if not title or not record_id or not path:
            continue
        chapter_ranges = item.get("chapter_ranges") or []
        revealed_at = chapter_ranges[0]["start"] if chapter_ranges else 1
        max_revealed = max(max_revealed, revealed_at)

        entries.append(
            {
                "normalized_name": nfkc(title),
                "matches": [
                    {
                        "surface": title,
                        "entity_ref": {"path": path, "record_id": record_id},
                        "entity_type": "character",
                        "name_type": "name",
                        "identity_status": "confirmed",
                        "chapter_ranges": [{"start": revealed_at, "end": revealed_at}],
                        "revealed_at": revealed_at,
                        "source_refs": [],
                        "basis_refs": [{"path": path, "record_id": record_id}],
                    }
                ],
            }
        )

    if not entries:
        print("characters/index.json 中没有可用的名字条目，未生成任何内容。")
        sys.exit(1)

    # 写入 name_lookup 分片（§4.5）
    names_dir = root / "navigation" / "names"
    names_dir.mkdir(parents=True, exist_ok=True)
    part = {
        "schema_version": "2.0",
        "novel_id": novel_id,
        "id": "names-part-0001",
        "kind": "name_lookup",
        "revision": 1,
        "safe_through": max_revealed,
        "entries": entries,
    }
    part_path = names_dir / "part-0001.json"
    part_path.write_text(
        json.dumps(part, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # 更新 index.json 的 shard_refs（§4.4）
    index_path = names_dir / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["shard_refs"] = [
        {"path": "navigation/names/part-0001.json", "record_id": "names-part-0001"}
    ]
    index_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"已生成 {len(entries)} 个名字 -> {part_path}")
    print(f"已更新 shard_refs -> {index_path}")


if __name__ == "__main__":
    main()
