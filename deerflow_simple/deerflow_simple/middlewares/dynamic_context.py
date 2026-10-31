"""DynamicContextMiddleware —— 注入当前日期与记忆。

对应 DeerFlow 的 `dynamic_context_middleware.py`。

职责：在每一轮开始时，把当前日期（以及可选的长期记忆）作为一个
`<system-reminder>` 注入到用户消息之前。框架持有的日期走 SystemMessage（system 权威），
用户可影响的记忆走 HumanMessage（不获得 system 权限）——这是 OWASP LLM01 的角色分离。

采用 ID-swap 技巧：用 SystemMessage 替换原 HumanMessage 的 id 位置，让 add_messages
把 reminder 插到正确位置，同时把真正的用户消息换成 `{id}__user` 的新 id。这样日期
只注入一次，后续同一天的轮次不会重复注入，从而保持 prefix-cache 友好。
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.runtime import Runtime

_REMINDER_KEY = "dynamic_context_reminder"


class DynamicContextMiddleware(AgentMiddleware):
    def __init__(self, config):
        super().__init__()
        self._config = config

    def _memory_block(self) -> str:
        """从记忆管理器取当前用户/线程的长期记忆上下文。"""
        if not self._config.memory_enabled:
            return ""
        from deerflow_simple.memory.manager import get_memory_manager

        return get_memory_manager(self._config).get_context()

    def before_agent(self, state, runtime: Runtime) -> dict | None:
        messages = list(state.get("messages", []))
        if not messages:
            return None

        # 找到最后一条真实的用户消息作为注入锚点
        target_idx = None
        for i in reversed(range(len(messages))):
            msg = messages[i]
            if isinstance(msg, HumanMessage) and not msg.id.endswith("__memory"):
                target_idx = i
                break
        if target_idx is None:
            return None

        current_date = datetime.now().strftime("%Y-%m-%d, %A")

        # 同一天已注入过则跳过（日期 reminder 已存在于历史中）
        for msg in messages:
            if isinstance(msg, SystemMessage) and msg.additional_kwargs.get(_REMINDER_KEY):
                return None

        reminder = f"<system-reminder>\n<current_date>{current_date}</current_date>\n</system-reminder>"
        original = messages[target_idx]
        stable_id = original.id or str(uuid4())

        result: list = [
            SystemMessage(
                content=reminder,
                id=stable_id,
                additional_kwargs={"hide_from_ui": True, _REMINDER_KEY: True},
            )
        ]
        memory_block = self._memory_block()
        if memory_block:
            result.append(
                HumanMessage(
                    content=f"<memory>\n{memory_block}\n</memory>",
                    id=f"{stable_id}__memory",
                    additional_kwargs={"hide_from_ui": True, _REMINDER_KEY: True},
                )
            )
        result.append(original.model_copy(update={"id": f"{stable_id}__user"}))
        return {"messages": result}
