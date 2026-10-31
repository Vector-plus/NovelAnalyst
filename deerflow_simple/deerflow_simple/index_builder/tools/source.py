"""A 类 · 原文读取工具（prescan 阶段 ScanVolReActAgent / StagePlanMergeAgent 用）。

锚定索引树根（index root），复用 :class:`ReadOnlyFs` 做路径穿越防护 + 纯只读。

对应设计文档《03-核心图设计_索引生成.md》§5.2 + 《04-prompt_第一阶段粗读.md》§2：
- ``list_dir(rel_path)``：列目录内容。
- ``read_file(rel_path)``：读任意文件原始内容（JSON 返回原文自行解析；txt 返回正文）。

这些是「通用文件系统工具，LLM 自主导航，工具不做路径推导和 JSON 解析」——
与 demo ``prescan_simple.py`` 的约定一致，让 Agent 自己解读 index.json / 章节正文。
"""

from __future__ import annotations

import json
from typing import Optional

from langchain_core.tools import tool

from deerflow_simple.narration.read_only import ReadOnlyFs


def build_source_tools(novel_root: str) -> list:
    """构建 prescan 阶段的只读工具集，锚定 novel_root（index root）。"""
    fs = ReadOnlyFs(novel_root)

    @tool
    def list_dir(rel_path: str = "") -> str:
        """列出索引树根目录下指定子目录的内容。

        参数:
            rel_path: 相对索引树根目录的路径，'' 表示根目录。

        返回:
            JSON 字符串：{"path": 路径, "entries": [{"name": 名称, "type": "dir"/"file", "size": 字节}]}
        """
        root = fs.root
        try:
            if rel_path in ("", "."):
                target = root
            else:
                from pathlib import Path as _P
                p = _P(rel_path)
                target = p.resolve() if p.is_absolute() else (root / p).resolve()
            if not target.is_relative_to(root):
                return "非法路径：越出索引树根目录"
            if not target.is_dir():
                return f"不是目录: {rel_path}"

            entries = []
            for entry in sorted(target.iterdir()):
                p = target / entry
                # entry 是 Path（PosixPath）对象，不能直接 json.dumps；取 .name 转字符串。
                if p.is_dir():
                    entries.append({"name": entry.name, "type": "dir"})
                else:
                    entries.append(
                        {"name": entry.name, "type": "file", "size": p.stat().st_size}
                    )
            return json.dumps({"path": rel_path or "/", "entries": entries}, ensure_ascii=False)
        except Exception as e:  # noqa: BLE001
            return f"(列出失败: {e})"

    @tool
    def read_file(rel_path: str, offset: int = 0, limit: int = 20000) -> str:
        """读取索引树根目录下任意文件的原始内容，不做任何解析。

        参数:
            rel_path: 相对索引树根目录的文件路径，如 'source/index.json' 或
                'source/vol-001/ch-000001.txt'。
            offset: 起始字符偏移（默认 0）。
            limit: 最多返回字符数（默认 20000，大文件保护）。

        返回:
            文件原始文本，前面附带一行元信息（文件总字符数、本次返回范围、是否截断）。
        """
        content = fs.read_file(rel_path)
        if content.startswith("("):
            return content
        total = len(content)
        seg = content[offset:offset + limit]
        truncated = offset + limit < total
        header = f"[文件 {rel_path} | 总字符 {total} | 返回 {offset}~{offset + len(seg)}]"
        if truncated:
            header += "（已截断，继续读请调大 offset）"
        return f"{header}\n{seg}"

    return [list_dir, read_file]


# ===========================================================================
# A 类 · deepread 专用原文读取工具（ChapterReActAgent 用）
# ===========================================================================
def build_deepread_read_tools(novel_root: str) -> list:
    """构建 deepread 的 A 类只读工具（read_source / read_source_window）。

    与 build_source_tools 的 list_dir/read_file（prescan 通用文件系统工具）不同：
    这里按 ``chapter_order`` 定位章节原文，段落按空行分隔（paragraph_rule=
    blank_line_separated，与 skeleton 切块一致）。

    对应 03 文档 §5.2 的 read_source / read_source_window。
    """
    from deerflow_simple.index_builder.tools.common import build_chapter_index

    fs = ReadOnlyFs(novel_root)
    chapter_index = build_chapter_index(novel_root)

    def _read_paragraphs(chapter_order: int) -> tuple[dict | None, list[str]]:
        info = chapter_index.get(chapter_order)
        if info is None:
            return None, []
        content = fs.read_file(info["path"])
        if content.startswith("("):
            return info, []
        paras = [p.strip() for p in content.split("\n\n") if p.strip()]
        return info, paras

    @tool
    def read_source(
        chapter_order: int,
        para_start: Optional[int] = None,
        para_end: Optional[int] = None,
    ) -> str:
        """读取指定章节的原文正文，支持按段落范围截取。

        参数:
            chapter_order: 章节号（1 起）。
            para_start: 起始段落号（1 起，含），不传则从第 1 段开始。
            para_end: 结束段落号（1 起，含），不传则到末尾。

        返回:
            原文正文，前面附一行元信息（章节号、标题、卷、段落总数、本次返回范围）。
        """
        info, paras = _read_paragraphs(chapter_order)
        if info is None:
            return f"章节不存在: {chapter_order}"
        if not paras:
            return f"章节 {chapter_order} 无正文段落"
        start = (para_start or 1) - 1
        end = para_end or len(paras)
        seg = paras[start:end]
        header = (
            f"[ch-{chapter_order:06d} | 标题:{info['title']} | 卷:{info['vol_id']} | "
            f"总段落 {len(paras)} | 返回段落 {start + 1}~{min(end, len(paras))}]"
        )
        return header + "\n\n" + "\n\n".join(seg)

    @tool
    def read_source_window(center_chapter: int, window: int = 2) -> str:
        """读取某章前后相邻章节的开头/结尾片段，用于核对跨章衔接。

        参数:
            center_chapter: 中心章节号。
            window: 前后各取多少章（默认 2）。

        返回:
            相邻章节的起止片段拼接文本。
        """
        parts = []
        for offset in range(-window, window + 1):
            ch = center_chapter + offset
            if ch < 1:
                continue
            info, paras = _read_paragraphs(ch)
            if info is None:
                parts.append(f"=== 第{ch}章：不存在 ===")
                continue
            head = "\n".join(paras[:3])
            tail = "\n".join(paras[-2:]) if len(paras) > 3 else ""
            parts.append(f"=== 第{ch}章 开头 ===\n{head}\n=== 第{ch}章 结尾 ===\n{tail}")
        return "\n\n".join(parts)

    return [read_source, read_source_window]
