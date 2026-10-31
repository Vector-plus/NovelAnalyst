"""LangSmith 追踪集成。

对应 DeerFlow 的 `tracing/factory.py::build_tracing_callbacks`。

精简版只保留 LangSmith 一条链路。LangChain / LangGraph 对 LangSmith 是**开箱即用**的：
只要设置了 `LANGSMITH_TRACING=true` 和 `LANGSMITH_API_KEY`，所有 model / tool / node
调用都会自动上报为一个 trace（一个 graph 运行 = 一个 trace，各节点为 child span）。

`build_tracing_callbacks()` 保留为扩展点：DeerFlow 在这里同时挂 LangSmith 与 Langfuse
的 callback，并把它们挂在 graph root（`config["callbacks"]`），这样子代理的运行也能
归组到父线程的同一个 session。精简版默认返回空列表（LangSmith 由内置机制接管），
但保留了挂载位置，便于后续扩展 Langfuse 等其它 provider。
"""

from __future__ import annotations

import os
from typing import Any


def langsmith_enabled() -> bool:
    """是否开启 LangSmith 追踪。"""
    return os.getenv("LANGSMITH_TRACING", "").lower() in {"true", "1", "yes"}


def build_tracing_callbacks() -> list[Any]:
    """返回挂在 graph root 的 callback handler 列表。

    精简版默认返回空列表，LangSmith 由 langchain 内置 env 驱动自动集成。
    """
    callbacks: list[Any] = []
    if not langsmith_enabled():
        return callbacks
    # LangChain 内置 LangSmith 集成已足够；此处保留扩展点（如 Langfuse）。
    return callbacks
