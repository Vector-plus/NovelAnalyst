#!/usr/bin/env python3
"""小说切块脚本：把原始小说 txt 按卷/章切分为 source/<卷>/ch-NNNNNN.txt 并生成原文清单。

遵循 novel-index 模板规范 v2.0（references/templates.md §5）。
仅使用 Python 3 标准库，零第三方依赖。

切块规则：
- 识别头部元信息（书名：/作者：），卷标记（第X卷），章标记（第X章，支持中文数字与阿拉伯数字）。
- 章节顺序号按阅读顺序从 1 连续递增（不使用原书中文数字）。
- 正文按空行切分非空段落，剥离段落首尾空白与全角缩进，统一 CRLF→LF。
- 每章写入 UTF-8 / LF 的单章文件，并计算 sha256 与 paragraph_count。
"""

import argparse
import hashlib
import json
import re
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

# 中文数字 -> 阿拉伯数字（支持到千级）
_CN_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}

# 卷/章标记：数字部分支持阿拉伯数字或中文数字
# 卷名兼容两种写法：
#   「第X卷」：数字在卷字之前（如「第一卷」）
#   「卷X」：数字在卷字之后（如诛仙原文「卷一」）
_VOL_RE = re.compile(r"^第\s*([0-9]+|[零〇一二三四五六七八九十百千万两]+)\s*卷\s*(.*)$")
_VOL_RE_ALT = re.compile(r"^卷\s*([0-9]+|[零〇一二三四五六七八九十百千万两]+)\s*(.*)$")
_CH_RE = re.compile(r"^第\s*([0-9]+|[零〇一二三四五六七八九十百千万两]+)\s*章\s*(.*)$")

_META_RE = {
    "title": re.compile(r"^书名\s*[:：]\s*(.*)$"),
    "author": re.compile(r"^作者\s*[:：]\s*(.*)$"),
}


def cn_num_to_int(text):
    """把中文数字串转换为整数；无法识别时返回 None。"""
    text = (text or "").strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    total = 0
    section = 0
    number = 0
    for ch in text:
        if ch in _CN_DIGITS:
            number = _CN_DIGITS[ch]
        elif ch in _CN_UNITS:
            unit = _CN_UNITS[ch]
            if unit == 10000:
                total = (total + section + (number if number else 1)) * 10000
                section = 0
                number = 0
            else:
                section += (number if number else 1) * unit
                number = 0
        else:
            return None
    return total + section + number


def json_dumps(obj):
    """规范 JSON 序列化：UTF-8、两空格缩进、键按 Unicode 码点排序、LF、末尾一个 LF。"""
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def write_json(path, obj):
    write_text(path, json_dumps(obj))


def split_paragraphs(body_lines):
    """切分正文为段落。

    段落边界：空行，或以空白/全角空格缩进开头的行（新段落起始）。
    段落内多行 strip 后直接拼接为一行（中文正文无空格需求）。
    输出文件段落间以空行分隔，符合 paragraph_rule=blank_line_separated。
    """
    paragraphs = []
    buf = []
    for raw in body_lines:
        line = raw.strip(" \t\r\n\u3000\ufeff")
        if line == "":
            if buf:
                paragraphs.append("".join(buf))
                buf = []
            continue
        if raw[0].isspace():
            if buf:
                paragraphs.append("".join(buf))
                buf = []
        buf.append(line)
    if buf:
        paragraphs.append("".join(buf))
    return paragraphs


def main(argv=None):
    parser = argparse.ArgumentParser(description="切分小说原文为单章文件并生成原文清单")
    parser.add_argument("--input", required=True, help="原始小说 txt 路径")
    parser.add_argument("--novel-root", default="novel", help="索引数据根目录，默认 novel")
    parser.add_argument("--novel-id", required=True, help="小说唯一 ID")
    parser.add_argument("--source-version", default="source-v1", help="绑定的原文版本")
    parser.add_argument("--title", help="书名；未提供时从文本提取")
    parser.add_argument("--author", help="作者；未提供时从文本提取")
    parser.add_argument("--encoding", default="utf-8", help="输入文本编码")
    args = parser.parse_args(argv)

    text = Path(args.input).read_text(encoding=args.encoding, errors="replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")

    title = args.title
    author = args.author

    volumes = []  # [{title, num, chapters: [{order, num, title, body_lines}]}]
    cur_vol = None
    cur_ch = None
    order_counter = 0

    for raw in lines:
        s = raw.strip()
        vm = _VOL_RE.match(s) or _VOL_RE_ALT.match(s)
        cm = _CH_RE.match(s)

        if vm:
            if cur_ch is not None:
                cur_vol["chapters"].append(cur_ch)
                cur_ch = None
            if cur_vol is not None and cur_vol["chapters"]:
                volumes.append(cur_vol)
            cur_vol = {
                "title": vm.group(2).strip() or None,
                "num": cn_num_to_int(vm.group(1)),
                "raw": s,
                "chapters": [],
            }
            continue

        if cm:
            if cur_ch is not None:
                cur_vol["chapters"].append(cur_ch)
                cur_ch = None
            if cur_vol is None:
                cur_vol = {"title": None, "num": None, "raw": None, "chapters": []}
            order_counter += 1
            cur_ch = {
                "order": order_counter,
                "num": cn_num_to_int(cm.group(1)),
                "title": cm.group(2).strip() or None,
                "body_lines": [],
            }
            continue

        if cur_ch is not None:
            cur_ch["body_lines"].append(raw)
            continue

        # 尚未进入任何章节：尝试提取元信息（书名 / 作者）
        if title is None:
            tm = _META_RE["title"].match(s)
            if tm:
                title = tm.group(1).strip() or None
        if author is None:
            am = _META_RE["author"].match(s)
            if am:
                author = am.group(1).strip() or None

    # flush 末尾未提交的章与卷
    if cur_ch is not None:
        cur_vol["chapters"].append(cur_ch)
        cur_ch = None
    if cur_vol is not None and cur_vol["chapters"]:
        volumes.append(cur_vol)

    if not volumes or order_counter == 0:
        print("错误：未识别到任何卷/章标记，请确认输入文件包含「第X卷」「第X章」标题。", file=sys.stderr)
        return 1

    novel_root = Path(args.novel_root)
    source_dir = novel_root / "source"
    source_dir.mkdir(parents=True, exist_ok=True)

    volume_entries = []
    for i, vol in enumerate(volumes, start=1):
        vol_id = f"vol-{i:03d}"
        vol_dir = source_dir / vol_id
        vol_dir.mkdir(parents=True, exist_ok=True)

        chapters = []
        start = end = None
        for ch in vol["chapters"]:
            ch_id = f"ch-{ch['order']:06d}"
            paragraphs = split_paragraphs(ch["body_lines"])
            content = ("\n\n".join(paragraphs) + "\n") if paragraphs else "\n"
            data = content.encode("utf-8")
            sha = hashlib.sha256(data).hexdigest()
            write_text(vol_dir / f"{ch_id}.txt", content)
            chapters.append({
                "id": ch_id,
                "chapter_order": ch["order"],
                "title": ch["title"],
                "path": f"source/{vol_id}/{ch_id}.txt",
                "safe_through": ch["order"],
                "sha256": sha,
                "paragraph_count": len(paragraphs),
            })
            if start is None:
                start = ch["order"]
            end = ch["order"]

        vol_safe = end if end is not None else 0
        write_json(vol_dir / "index.json", {
            "schema_version": SCHEMA_VERSION,
            "novel_id": args.novel_id,
            "id": f"source-{vol_id}",
            "kind": "source_chapters",
            "revision": 1,
            "safe_through": vol_safe,
            "volume_id": vol_id,
            "source_version": args.source_version,
            "encoding": "utf-8",
            "normalization": "lf",
            "paragraph_rule": "blank_line_separated",
            "chapters": chapters,
        })

        entry_title = vol["raw"] or f"第{i}卷"
        summary = f"第{start}—{end}章原文清单。"
        volume_entries.append({
            "target": {"path": f"source/{vol_id}/index.json", "record_id": f"source-{vol_id}"},
            "kind": "source_chapters",
            "title": entry_title,
            "summary": summary,
            "chapter_ranges": [{"start": start, "end": end}],
            "entity_refs": [],
            "tags": ["source"],
            "safe_through": vol_safe,
        })

    write_json(source_dir / "index.json", {
        "schema_version": SCHEMA_VERSION,
        "novel_id": args.novel_id,
        "id": "idx-source",
        "kind": "index",
        "revision": 1,
        "safe_through": order_counter,
        "title": "原文清单",
        "scope": {
            "chapter_ranges": [{"start": 1, "end": order_counter}],
            "subject_refs": [],
        },
        "coverage_status": "complete",
        "entries": volume_entries,
    })

    summary = {
        "novel_id": args.novel_id,
        "title": title,
        "author": author,
        "source_version": args.source_version,
        "volume_count": len(volumes),
        "chapter_count": order_counter,
        "volumes": [
            {
                "volume_id": f"vol-{j:03d}",
                "title": v["title"],
                "chapters": len(v["chapters"]),
                "chapter_range": [
                    v["chapters"][0]["order"],
                    v["chapters"][-1]["order"],
                ],
            }
            for j, v in enumerate(volumes, start=1)
        ],
    }
    sys.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
