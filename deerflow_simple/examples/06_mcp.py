"""06 MCP —— 演示 MCP Server 工具发现。

需要本机有 npx（Node.js）。使用 MCP 官方测试服务器 server-everything，
它暴露 add / subtract 等工具。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deerflow_simple import SimpleClient, SimpleConfig

config = SimpleConfig(
    sandbox_enabled=False,
    mcp_servers={
        "everything": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-everything"],
            "transport": "stdio",
        }
    },
)
client = SimpleClient(config)

print(client.chat("调用 MCP 的 add 工具，计算 40 + 2 等于多少。"))
