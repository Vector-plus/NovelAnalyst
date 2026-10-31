"""MemoryMiddleware —— 在 agent 运行结束后把对话入队，供长期记忆抽取。

对应 DeerFlow 的 `memory_middleware.py`。

职责：`after_agent` 时把本轮对话交给记忆管理器，管理器异步（简化版为同步）用 LLM
抽取可长期保存的事实。只抽取用户输入 + 最终助手回复，忽略中间的 tool 调用。
"""

from __future__ import annotations

from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime


class MemoryMiddleware(AgentMiddleware):
    def __init__(self, config):
        super().__init__()
        self._config = config

    def _thread_id(self, runtime: Runtime) -> str:
        context = getattr(runtime, "context", None)
        if isinstance(context, dict) and context.get("thread_id"):
            return str(context["thread_id"])
        try:
            from langgraph.config import get_config

            tid = get_config().get("configurable", {}).get("thread_id")
            if tid:
                return str(tid)
        except Exception:
            pass
        return "default"

    def after_agent(self, state, runtime: Runtime) -> dict | None:
        if not self._config.memory_enabled:
            return None
        messages = state.get("messages", [])
        if not messages:
            return None
        from deerflow_simple.memory.manager import get_memory_manager

        thread_id = self._thread_id(runtime) or "default"
        get_memory_manager(self._config).add(thread_id, messages)
        return None
