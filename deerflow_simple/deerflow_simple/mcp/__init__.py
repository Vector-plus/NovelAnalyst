"""MCP —— Model Context Protocol 服务器集成。

对应 DeerFlow 的 `mcp/`。精简版只保留 stdio 工具发现，用
`langchain-mcp-adapters` 的 `MultiServerMCPClient`。
"""

from deerflow_simple.mcp.tools import get_mcp_tools

__all__ = ["get_mcp_tools"]
