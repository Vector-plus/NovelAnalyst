#!/usr/bin/env python3
"""按章节范围计算并生成分片：章节导航、覆盖、问题三类分片。

遵循 novel-index 模板规范 v2.0（references/templates.md §4.3/§8.2/§8.3/§11.2）。
仅使用 Python 3 标准库，零第三方依赖。

生成：
- navigation/chapters/block-NNNN.json（IndexFile 骨架，entries 留空待精读填充）
- navigation/chapters/index.json（指向各 block 的入口）
- quality/coverage/block-NNNN.json（每章八个主题键全 not_analyzed）
- quality/issues/block-NNNN.json（issue_collection，issues=[]）
- quality/coverage.json、quality/issues.json（指向分片的入口）

章节范围升序、无重叠、合并相邻。
"""

import argparse
import json
import math
import sys
from pathlib import Path

# 统一 stdout/stderr 为 UTF-8，避免 locale 默认 ASCII 编码导致中文输出失败
import io
for _name in ("stdout", "stderr"):
    _stream = getattr(sys, _name)
    if hasattr(_stream, "buffer"):
        setattr(sys, _name, io.TextIOWrapper(
            _stream.buffer, encoding="utf-8", errors="replace", newline="\n"))

SCHEMA_VERSION = "2.0"

TOPIC_KEYS = ["plot", "characters", "factions", "settings", "relationships", "emotions", "events", "threads"]


def json_dumps(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def write_json(path, obj):
    write_text(path, json_dumps(obj))


def _index_file(novel_id, idx_id, title, entries, scope=None, coverage="partial", safe_through=0):
    return {
        "schema_version": SCHEMA_VERSION,
        "novel_id": novel_id,
        "id": idx_id,
        "kind": "index",
        "revision": 1,
        "safe_through": safe_through,
        "title": title,
        "scope": scope or {"chapter_ranges": [], "subject_refs": []},
        "coverage_status": coverage,
        "entries": entries,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="计算并生成章节导航/覆盖/问题分片")
    parser.add_argument("--novel-root", default="novel")
    parser.add_argument("--novel-id", required=True)
    parser.add_argument("--total", type=int, required=True, help="目标章节总数")
    parser.add_argument("--size", type=int, default=20, help="每片章节数，默认 20")
    parser.add_argument("--source-version", default="source-v1")
    args = parser.parse_args(argv)

    if args.total <= 0:
        print("错误：--total 必须为正整数。", file=sys.stderr)
        return 1
    if args.size <= 0:
        print("错误：--size 必须为正整数。", file=sys.stderr)
        return 1

    root = Path(args.novel_root)
    nid = args.novel_id
    block_count = math.ceil(args.total / args.size)

    chapters_index_entries = []
    coverage_index_entries = []
    issues_index_entries = []

    for i in range(1, block_count + 1):
        start = (i - 1) * args.size + 1
        end = min(i * args.size, args.total)
        block_label = f"block-{i:04d}"

        # navigation/chapters/block-NNNN.json（IndexFile 骨架，entries 留空）
        write_json(root / "navigation/chapters" / f"{block_label}.json", _index_file(
            nid,
            f"chapters-{block_label}",
            f"章节导航 {start}—{end}",
            [],
            scope={"chapter_ranges": [{"start": start, "end": end}], "subject_refs": []},
            coverage="partial",
            safe_through=0,
        ))

        chapters_index_entries.append({
            "target": {
                "path": f"navigation/chapters/{block_label}.json",
                "record_id": f"chapters-{block_label}",
            },
            "kind": "index",
            "title": f"章节 {start}—{end}",
            "summary": f"第{start}—{end}章章节导航分片。",
            "chapter_ranges": [{"start": start, "end": end}],
            "entity_refs": [],
            "tags": ["plot"],
            "safe_through": 0,
        })

        # quality/coverage/block-NNNN.json（§8.2）
        chapters = [
            {
                "chapter_id": f"ch-{o:06d}",
                "chapter_order": o,
                "topics": {k: "not_analyzed" for k in TOPIC_KEYS},
            }
            for o in range(start, end + 1)
        ]
        write_json(root / "quality/coverage" / f"{block_label}.json", {
            "schema_version": SCHEMA_VERSION,
            "novel_id": nid,
            "id": f"coverage-{block_label}",
            "kind": "coverage",
            "revision": 1,
            "safe_through": 0,
            "source_version": args.source_version,
            "chapters": chapters,
        })
        coverage_index_entries.append({
            "target": {
                "path": f"quality/coverage/{block_label}.json",
                "record_id": f"coverage-{block_label}",
            },
            "kind": "coverage",
            "title": f"覆盖 {start}—{end}",
            "summary": f"第{start}—{end}章覆盖状态分片。",
            "chapter_ranges": [{"start": start, "end": end}],
            "entity_refs": [],
            "tags": ["quality"],
            "safe_through": 0,
        })

        # quality/issues/block-NNNN.json（§8.3）
        write_json(root / "quality/issues" / f"{block_label}.json", {
            "schema_version": SCHEMA_VERSION,
            "novel_id": nid,
            "id": f"issues-{block_label}",
            "kind": "issue_collection",
            "revision": 1,
            "safe_through": 0,
            "issues": [],
        })
        issues_index_entries.append({
            "target": {
                "path": f"quality/issues/{block_label}.json",
                "record_id": f"issues-{block_label}",
            },
            "kind": "issue_collection",
            "title": f"问题 {start}—{end}",
            "summary": f"第{start}—{end}章问题分片。",
            "chapter_ranges": [{"start": start, "end": end}],
            "entity_refs": [],
            "tags": ["quality"],
            "safe_through": 0,
        })

    # navigation/chapters/index.json
    write_json(root / "navigation/chapters/index.json", _index_file(
        nid,
        "idx-chapters",
        "章节导航",
        chapters_index_entries,
        scope={"chapter_ranges": [{"start": 1, "end": args.total}], "subject_refs": []},
        coverage="partial",
    ))

    # quality/coverage.json、quality/issues.json
    write_json(root / "quality/coverage.json", _index_file(
        nid, "idx-coverage", "覆盖索引", coverage_index_entries, coverage="partial",
    ))
    write_json(root / "quality/issues.json", _index_file(
        nid, "idx-issues", "问题索引", issues_index_entries, coverage="partial",
    ))

    summary = {
        "novel_id": nid,
        "total": args.total,
        "size": args.size,
        "block_count": block_count,
        "chapters_blocks": [f"block-{i:04d}" for i in range(1, block_count + 1)],
    }
    sys.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
