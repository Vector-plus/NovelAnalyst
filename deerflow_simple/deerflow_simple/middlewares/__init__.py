"""Context Engineering —— middleware 链。

对应 DeerFlow 的 `agents/middlewares/`。middleware 是 deer-flow 的"灵魂"：
一条用户消息进入 graph 后，依次经过这些 middleware，最终发给模型的是被层层加工过的
请求。每个 middleware 只关心一件事，顺序由 `agent.py::build_middlewares` 决定。
"""

from deerflow_simple.middlewares.dynamic_context import DynamicContextMiddleware
from deerflow_simple.middlewares.durable_context import DurableContextMiddleware
from deerflow_simple.middlewares.memory_middleware import MemoryMiddleware
from deerflow_simple.middlewares.summarization import SummarizationMiddleware
from deerflow_simple.middlewares.system_coalescing import SystemMessageCoalescingMiddleware

__all__ = [
    "DynamicContextMiddleware",
    "DurableContextMiddleware",
    "MemoryMiddleware",
    "SummarizationMiddleware",
    "SystemMessageCoalescingMiddleware",
]
