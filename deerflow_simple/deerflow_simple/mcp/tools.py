"""MCP 工具加载（stdio 传输）。

对应 DeerFlow 的 `mcp/tools.py::get_mcp_tools`。同步封装了异步的
`MultiServerMCPClient`，便于在同步的 `build_agent` 中调用。
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


async def _load_mcp_tools(servers: dict) -> list:
    from langchain_mcp_adapters.client import MultiServerMCPClient

    client = MultiServerMCPClient(servers)
    return await client.get_tools()


def get_mcp_tools(servers: dict) -> list:
    """从配置的 MCP 服务器加载工具（同步入口）。"""
    if not servers:
        return []
    try:
        return asyncio.run(_load_mcp_tools(servers))
    except Exception as e:  # MCP 失败不应阻止整个 agent 构建
        logger.warning("加载 MCP 工具失败：%s", e)
        return []
