"""SystemMessageCoalescingMiddleware —— 合并多条 SystemMessage 为一条前导。

对应 DeerFlow 的 `system_message_coalescing_middleware.py`。

严格的 OpenAI 兼容后端（vLLM / SGLang / Qwen）会拒绝"非前导的多条 SystemMessage"。
DynamicContext 注入的日期 reminder 是 SystemMessage，而 create_agent 把静态
system_prompt 放在单独的 `request.system_message` 字段。本 middleware 在 wrap_model_call
阶段把两者合并成一条 leading SystemMessage，只改请求、不改 checkpoint。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage


def _flatten(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(item.get("text", "") if isinstance(item, dict) else str(item) for item in content)
    return str(content)


class SystemMessageCoalescingMiddleware(AgentMiddleware):
    def _coalesce(self, request: ModelRequest) -> ModelRequest:
        in_msg_systems = [m for m in request.messages if isinstance(m, SystemMessage)]
        if not in_msg_systems:
            return request  # 无 SystemMessage，system_message 已是唯一前导

        parts: list[SystemMessage] = []
        if request.system_message is not None:
            parts.append(request.system_message)
        parts.extend(in_msg_systems)

        merged_kwargs: dict = {}
        for p in parts:
            merged_kwargs.update(p.additional_kwargs or {})

        merged = SystemMessage(
            content="\n\n".join(_flatten(p.content) for p in parts),
            id=parts[0].id,
            additional_kwargs=merged_kwargs,
        )
        non_system = [m for m in request.messages if not isinstance(m, SystemMessage)]
        return request.override(system_message=merged, messages=non_system)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        return handler(self._coalesce(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        return await handler(self._coalesce(request))
