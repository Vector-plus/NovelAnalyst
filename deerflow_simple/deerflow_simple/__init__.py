"""deerflow_simple — 从 DeerFlow 核心设计提炼出的最小问答 agent 框架。

保留 DeerFlow 的核心子系统，但去掉 app 层、多余 provider 与企业级复杂度：

- Sub-Agents            (`deerflow_simple.subagents`)
- Progressive Skill Loading (`deerflow_simple.skills`)
- Skills & Tools        (`deerflow_simple.skills` + `deerflow_simple.sandbox`)
- Sandbox               (`deerflow_simple.sandbox`)
- Memory                (`deerflow_simple.memory`)
- Context Engineering   (`deerflow_simple.middlewares`)
- LangSmith             (`deerflow_simple.tracing`)
- MCP Server            (`deerflow_simple.mcp`)
- Worker 协程管理        (`deerflow_simple.runs`)

架构与 DeerFlow 一致：`langchain.agents.create_agent(model, tools, middleware,
system_prompt, state_schema, checkpointer)` + 有序的 `AgentMiddleware` 链；
run 的消费则通过 `RunManager` 准入 + 后台 `run_agent` 协程完成。
"""

from deerflow_simple.agent import build_agent
from deerflow_simple.checkpointer import acheckpointer_context, checkpointer_context
from deerflow_simple.client import SimpleClient
from deerflow_simple.config import SimpleConfig
from deerflow_simple.runs import (
    ConflictError,
    RunManager,
    RunRecord,
    RunStartOutcome,
    RunStatus,
    UnsupportedStrategyError,
)

__all__ = [
    "SimpleConfig",
    "build_agent",
    "checkpointer_context",
    "acheckpointer_context",
    "SimpleClient",
    "RunManager",
    "RunRecord",
    "RunStartOutcome",
    "RunStatus",
    "ConflictError",
    "UnsupportedStrategyError",
]
__version__ = "0.1.0"
