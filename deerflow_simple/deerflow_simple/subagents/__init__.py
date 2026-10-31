"""Sub-Agents —— 子代理委派。

对应 DeerFlow 的 `subagents/`。精简版保留核心：`task` 工具把子任务委派给一个
一次性编译的独立子代理 graph，隔离执行后返回结果。
"""

from deerflow_simple.subagents.executor import SubagentExecutor
from deerflow_simple.subagents.task_tool import build_task_tool

__all__ = ["SubagentExecutor", "build_task_tool"]
