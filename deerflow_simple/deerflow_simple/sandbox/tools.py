"""沙箱工具（bash / read_file / write_file / ls）。

对应 DeerFlow 的 `sandbox/tools.py`。用 closure 把工具绑定到具体的沙箱实例。
"""

from __future__ import annotations

from langchain_core.tools import tool

from deerflow_simple.sandbox.sandbox import Sandbox


def build_sandbox_tools(sandbox: Sandbox):
    @tool
    def bash(command: str) -> str:
        """在沙箱中执行一条 shell 命令（如 `ls`、`cat file.txt`、`python script.py`），返回 stdout+stderr。"""
        return sandbox.execute_command(command)

    @tool
    def read_file(path: str) -> str:
        """读取沙箱中的一个文本文件内容（相对路径）。"""
        return sandbox.read_file(path)

    @tool
    def write_file(path: str, content: str) -> str:
        """把内容写入沙箱文件（相对路径，会自动创建目录）。"""
        return sandbox.write_file(path, content)

    @tool
    def ls(path: str = ".") -> str:
        """列出沙箱目录内容。"""
        return sandbox.list_dir(path)

    return [bash, read_file, write_file, ls]
