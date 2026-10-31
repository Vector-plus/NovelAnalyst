"""09 业务工具注入 —— 演示 extra_tools（把上层工具挂进 lead_agent）。

M0 改造点：`SimpleClient(..., extra_tools=[...])` 把业务工具注入 lead_agent，
工具会在 MCP 之后、`_dedupe_tools` 之前合并进工具列表。

这是 M1 的关键入口——后续 `generate_narration` / `build_novel_index`
这两个工作流工具，就通过 `extra_tools` 挂进 lead_agent。

用法：
    python examples/09_extra_tools.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from langchain_core.tools import tool

from deerflow_simple import SimpleClient, SimpleConfig


# 一个演示用的业务工具：真正的工作流入口（如 generate_narration）同理定义。
@tool
def get_project_version() -> str:
    """返回 deerflow-simple 项目的当前版本与已启用能力。"""
    return "deerflow-simple v0.1.0（M0：支持 extra_tools 注入 + checkpointer 可配置化）"


config = SimpleConfig(
    sandbox_enabled=False,      # 关闭通用沙箱，聚焦验证 extra_tools
    subagents_enabled=False,
    summarization_enabled=False,
)
# 通过 SimpleClient 的 extra_tools 参数把业务工具注入 lead_agent
client = SimpleClient(config, extra_tools=[get_project_version])

print(client.chat("请调用 get_project_version 工具，告诉我项目版本信息。"))
client.close()
