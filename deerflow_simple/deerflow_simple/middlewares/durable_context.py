"""DurableContextMiddleware —— 把摘要/技能上下文投影进模型请求。

对应 DeerFlow 的 `durable_context_middleware.py`。

职责分两半：
1. capture（before_model）：从消息历史里扫描出"已加载的技能"（read_file 读到了
   SKILL.md），写进 `skill_context` 通道——这样技能加载状态在摘要压缩后依然存活。
2. inject（wrap_model_call）：把 `summary_text` / `skill_context` / `delegations`
   渲染成一段隐藏的 HumanMessage，插入到请求里（不写回 state，checkpoint 干净）。

注入内容一律按"不可信数据"处理，绝不赋予 system 权威。
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.runtime import Runtime

_DURABLE_CONTEXT_KEY = "durable_context_data"
_SKILL_FRONTMATTER = re.compile(r"^name:\s*(.+)$|^description:\s*(.+)$", re.MULTILINE)


def _extract_skills(messages: list) -> list[dict]:
    """扫描 read_file 工具读取 SKILL.md 的调用，提取技能引用。

    对应 DeerFlow 的 `skill_context.py::extract_skills` 的极简版：只识别
    `read_file` 工具、且路径以 `SKILL.md` 结尾的调用。
    """
    skills: list[dict] = []
    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        if getattr(msg, "name", None) != "read_file":
            continue
        content = msg.content if isinstance(msg.content, str) else ""
        if "SKILL.md" not in content and "SKILL.md" not in str(getattr(msg, "additional_kwargs", {})):
            continue
        name = desc = None
        for m in _SKILL_FRONTMATTER.finditer(content):
            if m.group(1):
                name = m.group(1).strip()
            elif m.group(2):
                desc = m.group(2).strip()
        if name:
            skills.append({"name": name, "path": name, "description": desc or ""})
    return skills


class DurableContextMiddleware(AgentMiddleware):
    def __init__(self, config):
        super().__init__()
        self._config = config

    # ---- capture ----
    def before_model(self, state, runtime: Runtime) -> dict | None:
        skills = _extract_skills(state.get("messages", []))
        if skills:
            return {"skill_context": skills}
        return None

    # ---- inject ----
    def _inject(self, request: ModelRequest) -> ModelRequest:
        state = request.state or {}
        parts: list[str] = []

        summary = state.get("summary_text")
        if summary:
            parts.append(f"## 对话摘要\n{summary}")

        skills = state.get("skill_context") or []
        if skills:
            lines = ["## 已加载的技能"]
            for s in skills:
                lines.append(f"- {s['name']}: {s['description']}")
            parts.append("\n".join(lines))

        delegations = state.get("delegations") or []
        if delegations:
            lines = ["## 子代理委派记录"]
            for d in delegations:
                lines.append(f"- {d.get('description', '')} → {d.get('status', '')}")
            parts.append("\n".join(lines))

        if not parts:
            return request

        block = "<durable_context_data>\n" + "\n\n".join(parts) + "\n</durable_context_data>"
        messages = list(request.messages) + [
            HumanMessage(
                content=block,
                additional_kwargs={"hide_from_ui": True, _DURABLE_CONTEXT_KEY: True},
            )
        ]
        return request.override(messages=messages)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        return handler(self._inject(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        return await handler(self._inject(request))
