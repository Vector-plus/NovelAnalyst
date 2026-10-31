"""ReadOnlyFs —— 解说词只读文件访问器。

解说词是纯只读消费端：它需要读取 `novel_root` 指向的索引树（manifest、navigation、
names、ledger、原文等），但**绝不写入**。这里提供一个只读文件访问器，作为所有
narration 工具的地基。

与 `sandbox.LocalSandbox` 的区别：LocalSandbox 把绝对路径强制压进 workspace（用于
通用 agent 的沙箱隔离），而解说词需要访问 `novel_root` 这个**任意位置的绝对路径**，
因此不能复用 LocalSandbox，需要独立实现。

安全护栏（确定性，绝不交给 LLM）：
- **路径穿越防护**：任何解析后的路径必须位于 `novel_root` 内，否则拒绝访问。
- **纯只读**：只提供 read_file / list_dir / exists，没有任何写方法。
"""

from __future__ import annotations

from pathlib import Path


class ReadOnlyFs:
    """在 `novel_root` 内做只读文件访问，防路径穿越。"""

    def __init__(self, novel_root: str | Path):
        self._root = Path(novel_root).expanduser().resolve()
        if not self._root.is_dir():
            raise ValueError(f"novel_root 不是有效目录: {novel_root}")

    @property
    def root(self) -> Path:
        return self._root

    def _resolve(self, path: str) -> Path:
        """把 path 解析到 novel_root 内的绝对路径，越界则抛 ValueError。"""
        p = Path(path)
        if p.is_absolute():
            resolved = p.resolve()
        else:
            resolved = (self._root / p).resolve()
        # 路径穿越防护：解析结果必须仍位于 novel_root 内
        if not resolved.is_relative_to(self._root):
            raise ValueError(f"路径越界，拒绝访问: {path}")
        return resolved

    def read_file(self, path: str) -> str:
        """读取 novel_root 内的一个文本文件，返回内容或错误提示。"""
        try:
            resolved = self._resolve(path)
        except ValueError as e:
            return f"(拒绝访问: {e})"
        if not resolved.exists():
            return f"(文件不存在: {path})"
        if not resolved.is_file():
            return f"(不是文件: {path})"
        try:
            return resolved.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return f"(读取失败: {e})"

    def list_dir(self, path: str = ".") -> str:
        """列出 novel_root 内目录的条目（相对 novel_root 的路径）。"""
        try:
            resolved = self._resolve(path)
        except ValueError as e:
            return f"(拒绝访问: {e})"
        if not resolved.exists():
            return "(空目录)"
        if not resolved.is_dir():
            return f"(不是目录: {path})"
        entries = sorted(
            x.relative_to(self._root).as_posix() for x in resolved.iterdir()
        )
        return "\n".join(entries) if entries else "(空目录)"

    def exists(self, path: str) -> bool:
        """判断路径是否存在（越界视为不存在）。"""
        try:
            return self._resolve(path).exists()
        except ValueError:
            return False

    def is_dir(self, path: str) -> bool:
        """判断路径是否为目录（越界或不存在均视为 False）。"""
        try:
            return self._resolve(path).is_dir()
        except ValueError:
            return False
