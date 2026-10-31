"""记忆工具（memory_search / memory_add）。

对应 DeerFlow 的 `agents/memory/tools.py` 的极简版，只有检索和新增两条。
"""

from __future__ import annotations

from langchain_core.tools import tool

from deerflow_simple.config import SimpleConfig
from deerflow_simple.memory.manager import get_memory_manager


def build_memory_tools(config: SimpleConfig):
    manager = get_memory_manager(config)

    @tool
    def memory_search(query: str) -> str:
        """搜索长期记忆，返回与 query 相关的事实。"""
        return manager.search(query)

    @tool
    def memory_add(content: str) -> str:
        """把一条事实写入长期记忆。"""
        return manager.add_fact(content)

    return [memory_search, memory_add]
