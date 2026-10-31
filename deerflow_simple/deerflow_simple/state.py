"""线程状态 schema。

对应 DeerFlow 的 `agents/thread_state.py::ThreadState`。继承 LangChain 内置的
`AgentState`（含 `messages` 通道，使用 add_messages reducer），新增三个通道：

- `summary_text`   —— 摘要文本（LastValue，每次摘要覆盖）
- `skill_context`  —— 已加载技能引用（按 path 去重，最近读取优先）
- `delegations`    —— 子代理委派记录（追加，容量上限）

理解 reducer 是理解"状态如何在多轮/子代理间累积"的关键。
"""

from __future__ import annotations

from typing import Annotated, Any, NotRequired, TypedDict

from langchain.agents import AgentState

_SKILL_CONTEXT_MAX_ENTRIES = 8
_DELEGATION_MAX_ENTRIES = 50


class SkillEntry(TypedDict):
    """技能上下文条目：只存引用，不存 SKILL.md 正文。"""

    name: str
    path: str
    description: str


def merge_skill_context(existing: list[SkillEntry] | None, new: list[SkillEntry] | None) -> list[SkillEntry]:
    """按 path 去重，最近读取的条目靠后、保留最新。"""
    if not new:
        return existing or []
    by_path: dict[str, SkillEntry] = {}
    order: list[str] = []
    for entry in [*(existing or []), *new]:
        path = entry["path"]
        if path not in by_path:
            order.append(path)
        by_path[path] = entry
    merged = [by_path[path] for path in order]
    return merged[-_SKILL_CONTEXT_MAX_ENTRIES:]


def merge_delegations(existing: list[dict] | None, new: list[dict] | None) -> list[dict]:
    """追加委派记录，同 id 覆盖，保留容量上限。"""
    if not new:
        return existing or []
    by_id: dict[str, dict] = {}
    order: list[str] = []
    for entry in [*(existing or []), *new]:
        entry_id = entry["id"]
        if entry_id not in by_id:
            order.append(entry_id)
        by_id[entry_id] = entry
    merged = [by_id[entry_id] for entry_id in order]
    return merged[-_DELEGATION_MAX_ENTRIES:]


class ThreadState(AgentState):
    """精简版线程状态。"""

    summary_text: NotRequired[str | None]
    skill_context: Annotated[list[SkillEntry], merge_skill_context]
    delegations: Annotated[list[dict], merge_delegations]
    # 当前对话绑定的小说空间 id（novel_id）。由代码在创建对话时传入，工具通过
    # InjectedState("novel_id") 注入，不交给 LLM 决策。
    novel_id: NotRequired[str | None]


def _default_context() -> dict[str, Any]:
    return {}
