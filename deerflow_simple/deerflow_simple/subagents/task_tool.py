"""task 工具 —— 把任务委派给子代理。

对应 DeerFlow 的 `tools/builtins/task_tool.py`。用 closure 绑定 executor。
"""

from __future__ import annotations

from langchain_core.tools import tool

from deerflow_simple.subagents.executor import SubagentExecutor


def build_task_tool(executor: SubagentExecutor):
    @tool
    def task(description: str) -> str:
        """把独立子任务委派给一个专用子代理执行。适用于：并行处理多个独立问题、
        需要隔离上下文的任务、需要专注完成的复杂子任务。完成后返回子代理的结果。"""
        return executor.execute(description)

    return task
