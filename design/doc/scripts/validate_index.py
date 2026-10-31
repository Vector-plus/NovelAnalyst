#!/usr/bin/env python3
"""校验小说索引目录的 JSON 结构、FileMeta、路径安全与章节范围。

遵循 novel-index 模板规范 v2.0（references/templates.md §3/§11.3）。
仅使用 Python 3 标准库，零第三方依赖。

校验项：
- JSON 可解析且无重复键。
- FileMeta 必填字段齐全，schema_version=="2.0"，revision>=1，safe_through>=0。
- 所有 "path" 字段为相对路径，不含绝对路径、`..` 段或外部 URL。
- 含整数 start/end 的对象满足 end>=start。
- 可选 --check-refs：校验 Ref 指向的文件存在且含对应 record_id。
- 可选 --novel-id / --source-version：校验一致性。

退出码：无问题为 0，存在问题为 1。
"""

import argparse
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

REQUIRED_META = ["schema_version", "novel_id", "id", "kind", "revision", "safe_through"]

_ABS_RE = re.compile(r"^(/|[A-Za-z]:[\\/]|\\\\)")
_URL_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")


def _no_dup_pairs(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise ValueError(f"重复键: {k}")
        d[k] = v
    return d


def _check_path(p, file, issues):
    if not isinstance(p, str):
        return
    if p == "":
        return
    if _ABS_RE.match(p):
        issues.append(f"{file}: 非法 path（绝对路径）: {p}")
        return
    if _URL_RE.match(p) or "://" in p:
        issues.append(f"{file}: 非法 path（外部 URL）: {p}")
        return
    if ".." in p.split("/"):
        issues.append(f"{file}: 非法 path（含 .. 段）: {p}")


def _walk(node, file, issues, refs):
    if isinstance(node, dict):
        if "path" in node and isinstance(node["path"], str):
            _check_path(node["path"], file, issues)
        if "path" in node and "record_id" in node and isinstance(node["record_id"], str):
            refs.append((node["path"], node["record_id"], file))
        if "start" in node and "end" in node:
            s, e = node.get("start"), node.get("end")
            if type(s) is int and type(e) is int and e < s:
                issues.append(f"{file}: 范围非法 end<start: {node}")
        for v in node.values():
            _walk(v, file, issues, refs)
    elif isinstance(node, list):
        for item in node:
            _walk(item, file, issues, refs)


def _check_meta(obj, file, issues):
    for k in REQUIRED_META:
        if k not in obj:
            issues.append(f"{file}: 缺少 FileMeta 字段 {k}")
            return
    if obj.get("schema_version") != SCHEMA_VERSION:
        issues.append(f"{file}: schema_version 应为 {SCHEMA_VERSION}，实际 {obj.get('schema_version')!r}")
    if type(obj.get("revision")) is not int or obj["revision"] < 1:
        issues.append(f"{file}: revision 应为 >=1 的整数")
    if type(obj.get("safe_through")) is not int or obj["safe_through"] < 0:
        issues.append(f"{file}: safe_through 应为 >=0 的整数")


def main(argv=None):
    parser = argparse.ArgumentParser(description="校验小说索引目录")
    parser.add_argument("--root", required=True)
    parser.add_argument("--novel-id", default=None)
    parser.add_argument("--source-version", default=None)
    parser.add_argument("--check-refs", action="store_true", help="跨文件引用存在性检查")
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not root.exists():
        print(f"错误：目录不存在 {root}", file=sys.stderr)
        return 1

    issues = []
    refs = []
    files = sorted(root.rglob("*.json"))
    if not files:
        print("警告：未发现任何 .json 文件。", file=sys.stderr)

    for f in files:
        rel = f.relative_to(root).as_posix()
        try:
            text = f.read_text(encoding="utf-8")
            obj = json.loads(text, object_pairs_hook=_no_dup_pairs)
        except ValueError as e:
            issues.append(f"{rel}: JSON 解析失败: {e}")
            continue
        except Exception as e:  # noqa: BLE001
            issues.append(f"{rel}: 读取失败: {e}")
            continue

        if not isinstance(obj, dict):
            issues.append(f"{rel}: 顶层应为对象")
            continue
        _check_meta(obj, rel, issues)
        if args.novel_id and obj.get("novel_id") != args.novel_id:
            issues.append(f"{rel}: novel_id 不一致，期望 {args.novel_id}，实际 {obj.get('novel_id')!r}")
        if (
            args.source_version
            and "source_version" in obj
            and obj.get("source_version") is not None
            and obj.get("source_version") != args.source_version
        ):
            issues.append(f"{rel}: source_version 不一致，期望 {args.source_version}，实际 {obj.get('source_version')!r}")
        _walk(obj, rel, issues, refs)

    if args.check_refs:
        for path, record_id, src in refs:
            target = root / path
            if not target.exists():
                issues.append(f"{src}: 引用目标不存在 {path}")
                continue
            try:
                content = target.read_text(encoding="utf-8")
            except Exception:  # noqa: BLE001
                issues.append(f"{src}: 引用目标不可读 {path}")
                continue
            if record_id not in content:
                issues.append(f"{src}: 引用 record_id 未在目标中找到 {path}#{record_id}")

    if issues:
        for line in issues:
            print(line)
        print(f"共 {len(issues)} 个问题。")
        return 1

    print(f"校验通过：{len(files)} 个 JSON 文件，{len(refs)} 条引用" +
          ("（含引用存在性检查）" if args.check_refs else "") + "。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
