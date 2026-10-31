"""Sandbox 接口与 LocalSandbox 实现。"""

from __future__ import annotations

import os
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path


class Sandbox(ABC):
    """沙箱统一接口（对应 DeerFlow 的 `sandbox/sandbox.py::Sandbox`）。"""

    @abstractmethod
    def execute_command(self, command: str, env: dict | None = None) -> str: ...

    @abstractmethod
    def read_file(self, path: str) -> str: ...

    @abstractmethod
    def write_file(self, path: str, content: str) -> str: ...

    @abstractmethod
    def list_dir(self, path: str = ".") -> str: ...


class LocalSandbox(Sandbox):
    """本地沙箱：在 workspace 目录内执行命令、读写文件。

    不是安全隔离，仅用于学习演示。
    """

    def __init__(self, workspace: Path):
        self._workspace = workspace
        self._workspace.mkdir(parents=True, exist_ok=True)

    def _resolve(self, path: str) -> Path:
        p = Path(path)
        resolved = p.resolve() if p.is_absolute() else (self._workspace / p).resolve()
        # 路径穿越防护：解析结果必须仍位于 workspace 内（拒绝 ../ 等）
        if not resolved.is_relative_to(self._workspace):
            raise ValueError(f"路径越界，拒绝访问: {path}")
        return resolved

    def execute_command(self, command: str, env: dict | None = None) -> str:
        merged_env = {**os.environ, **(env or {})}
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=False,  # 字节模式：避免 text=True 在非 UTF-8 输出上抛 UnicodeDecodeError
                cwd=self._workspace,
                env=merged_env,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            return "命令执行超时（60s）"
        raw = (result.stdout or b"") + (result.stderr or b"")
        # 容错解码：优先 UTF-8，失败用 replace 兜底。
        # 这样 LLM 误读二进制文件（如 sqlite db）时不会让整个 run 崩溃，只是返回乱码。
        try:
            out = raw.decode("utf-8")
        except UnicodeDecodeError:
            out = raw.decode("utf-8", errors="replace")
        out = out.strip()
        return out if out else "(无输出)"

    def read_file(self, path: str) -> str:
        try:
            p = self._resolve(path)
        except ValueError as e:
            return f"(拒绝访问: {e})"
        if not p.exists():
            return f"(文件不存在: {path})"
        try:
            return p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return f"(读取失败: {e})"

    def write_file(self, path: str, content: str) -> str:
        try:
            p = self._resolve(path)
        except ValueError as e:
            return f"(拒绝访问: {e})"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"已写入 {path}（{len(content)} 字符）"

    def list_dir(self, path: str = ".") -> str:
        try:
            p = self._resolve(path)
        except ValueError as e:
            return f"(拒绝访问: {e})"
        if not p.exists():
            return "(空目录)"
        entries = sorted(x.relative_to(self._workspace).as_posix() for x in p.iterdir())
        return "\n".join(entries) if entries else "(空目录)"
