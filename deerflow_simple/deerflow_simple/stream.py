"""流式事件协议 + 跨层事件桥 + 事件解析器。

负责两件事：

1. **统一事件协议**：lead_agent 与内层 NarrationAgent 都产出同一套结构化事件，
   前端无需区分来源即可渲染「模型文本 / 推理内容 / 工具调用 / 工具返回」。

2. **跨层事件桥**：lead_agent 消费流时，通过 ``set_stream_emitter`` 把 ``on_event``
   回调绑定到当前 async task 的 ``contextvars``；内层工具（如 ``generate_narration``）
   在同一个 task 内调用 ``emit_event``，即可把内层 NarrationAgent 的事件透传回
   lead_agent 的事件通道，最终由同一份 ``on_event`` 回调统一对外输出。

事件协议（均为 ``dict``）：

- ``message``      ：模型文本 delta（token 级），字段 ``content``。
- ``reasoning``    ：模型推理内容 delta（reasoning_content，token 级），字段 ``content``。
- ``tool_call``    ：一次完整工具调用，字段 ``name`` / ``args``（dict 或字符串）/ ``tool_call_id``。
- ``tool_result``  ：一次工具返回，字段 ``name`` / ``content`` / ``tool_call_id``。
- ``node``         ：长任务（索引生成）的节点进度，字段 ``node``（节点名）/ ``status``（enter|exit）。
- ``done``         ：终态，字段 ``status`` / ``result`` / ``error``。

每个事件都带 ``source`` 字段：``lead``（lead_agent 自身）/ ``narration``（内层透传）/
``index``（索引生成长任务）。
"""

from __future__ import annotations

import json
from contextvars import ContextVar
from typing import Any, Callable

from langchain_core.messages import AIMessageChunk, ToolMessage

# ---------------------------------------------------------------------------
# 事件类型常量
# ---------------------------------------------------------------------------
EVENT_MESSAGE = "message"
EVENT_REASONING = "reasoning"
EVENT_TOOL_CALL = "tool_call"
EVENT_TOOL_RESULT = "tool_result"
EVENT_NODE = "node"
EVENT_DONE = "done"

# ---------------------------------------------------------------------------
# 事件来源
# ---------------------------------------------------------------------------
SOURCE_LEAD = "lead"
SOURCE_NARRATION = "narration"
SOURCE_INDEX = "index"

# ---------------------------------------------------------------------------
# contextvar 事件桥
# ---------------------------------------------------------------------------
# 绑定到当前 async task 的事件发射器。lead_agent 的 worker 在消费流前设置，
# 内层工具（generate_narration）在同一个 task 内通过 emit_event 透传事件。
# 同一 async task 内 contextvar 自动传播，无需在 tool schema 里暴露回调参数。
_stream_emitter: ContextVar[Callable[[dict[str, Any]], None] | None] = ContextVar(
    "deerflow_stream_emitter", default=None
)


def set_stream_emitter(emitter: Callable[[dict[str, Any]], None] | None) -> None:
    """绑定/解绑当前 async task 的事件发射器（worker 消费流前后调用）。"""
    _stream_emitter.set(emitter)


def emit_event(event: dict[str, Any]) -> None:
    """向当前 task 的事件发射器发送事件；未绑定发射器时静默忽略。

    内层工具（generate_narration）在消费内层流时调用本函数，把事件透传回
    lead_agent 的事件通道。
    """
    emitter = _stream_emitter.get()
    if emitter is not None:
        emitter(event)


def _parse_tool_args(args_str: str) -> Any:
    """把工具调用参数 JSON 字符串解析为 dict；解析失败保留原字符串。"""
    if not args_str:
        return {}
    try:
        return json.loads(args_str)
    except json.JSONDecodeError:
        return args_str


def _try_complete_args(args_str: str) -> tuple[bool, Any]:
    """判断流式累加中的 tool_call args 是否已完整，返回 ``(是否完整, 解析结果)``。

    ``tool_call_chunks`` 的 args 是逐片流出的（第一个 chunk 通常 args 为空，后续
    逐片累加），只有 ``json.loads`` 成功才算完整。返回 ``(False, ...)`` 表示还在
    累加中，不应据此 emit 完整的 ``tool_call`` 事件。
    """
    if not args_str:
        return False, {}
    try:
        return True, json.loads(args_str)
    except json.JSONDecodeError:
        return False, args_str


def parse_stream_chunk(
    message: Any,
    pending_tool_calls: dict[int, dict[str, Any]],
    source: str,
) -> tuple[list[dict[str, Any]], bool]:
    """把 ``stream_mode="messages"`` 的一个 ``(message, metadata)`` 解析成事件列表。

    Args:
        message: AIMessageChunk（含 content / reasoning_content / tool_call_chunks）
            或 ToolMessage（工具返回）。
        pending_tool_calls: 按 tool_call index 累加参数的缓冲区（跨 chunk 复用）。
        source: 事件来源（``SOURCE_LEAD`` 或 ``SOURCE_NARRATION``）。

    Returns:
        (events, is_tool_activity)：events 是本 chunk 产出的事件列表；
        is_tool_activity 表示本 chunk 涉及工具活动（用于调用方重置最终答案累计）。
    """
    events: list[dict[str, Any]] = []
    is_tool_activity = False

    if isinstance(message, AIMessageChunk):
        # 1) 模型文本 delta（token 级）
        content = message.content
        if isinstance(content, str) and content:
            events.append({"type": EVENT_MESSAGE, "content": content, "source": source})

        # 2) 推理内容 delta（reasoning_content，DeepSeek-R1 等，token 级）
        reasoning = (message.additional_kwargs or {}).get("reasoning_content")
        if reasoning:
            events.append({"type": EVENT_REASONING, "content": reasoning, "source": source})

        # 3) 工具调用 chunks：按 index 累加 name / id / args
        for tc in message.tool_call_chunks or []:
            is_tool_activity = True
            idx = tc.get("index") or 0
            if idx not in pending_tool_calls:
                pending_tool_calls[idx] = {
                    "id": None,
                    "name": "",
                    "args": "",
                    "emitted": False,
                }
            entry = pending_tool_calls[idx]
            if tc.get("id"):
                entry["id"] = tc["id"]
            if tc.get("name"):
                entry["name"] = tc["name"]
            if tc.get("args"):
                entry["args"] += tc["args"]

            # 尽早 emit tool_call：name 已确定且 args 累加完整（可 JSON 解析）时立即产出。
            # 这样 lead_agent 调用工具（如 generate_narration）的 tool_call 事件会在
            # 「工具执行前」就出现在事件流里，而不是等 ToolMessage 才出现（否则会被
            # 工具内部透传的内层事件淹没、造成「看不到工具调用」的错觉）。
            if entry["name"] and not entry.get("emitted"):
                complete, args = _try_complete_args(entry["args"])
                if complete:
                    entry["emitted"] = True
                    events.append(
                        {
                            "type": EVENT_TOOL_CALL,
                            "name": entry["name"],
                            "args": args,
                            "tool_call_id": entry["id"],
                            "source": source,
                        }
                    )

    elif isinstance(message, ToolMessage):
        is_tool_activity = True
        name = message.name or ""
        tool_call_id = message.tool_call_id or ""

        # 找到对应的 pending 条目（通常已在上方 emit 过 tool_call）
        matched = None
        for tc in pending_tool_calls.values():
            if tc.get("id") and tc.get("id") == tool_call_id:
                matched = tc
                break
        if matched is None:
            for tc in pending_tool_calls.values():
                if tc.get("name") == name:
                    matched = tc
                    break

        # 兜底：若 tool_call 尚未在 AIMessageChunk 阶段 emit（如无参工具、args 始终
        # 未解析成功等极端情况），这里补 emit 一次完整的 tool_call。
        if matched is not None:
            if not matched.get("emitted"):
                matched["emitted"] = True
                events.append(
                    {
                        "type": EVENT_TOOL_CALL,
                        "name": matched["name"] or name,
                        "args": _parse_tool_args(matched["args"]),
                        "tool_call_id": tool_call_id,
                        "source": source,
                    }
                )
        else:
            events.append(
                {
                    "type": EVENT_TOOL_CALL,
                    "name": name,
                    "args": {},
                    "tool_call_id": tool_call_id,
                    "source": source,
                }
            )

        result_content = message.content
        if not isinstance(result_content, str):
            result_content = str(result_content)
        events.append(
            {
                "type": EVENT_TOOL_RESULT,
                "name": name,
                "content": result_content,
                "tool_call_id": tool_call_id,
                "source": source,
            }
        )

    return events, is_tool_activity


# ---------------------------------------------------------------------------
# 预算守护（token 估算 + 工具调用计数）
# ---------------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    """粗略估算一段文本的 token 数。

    中文场景下 1 个汉字 ≈ 1 token；英文/数字/标点约 4 字符 ≈ 1 token。
    用「非 ASCII 按 1 字 1 token、ASCII 按 4 字符 1 token」做保守估算，
    不引入 tiktoken 等额外依赖，实用即可。用于预算守护，允许少量误差。
    """
    if not text:
        return 0
    wide = sum(1 for c in text if ord(c) > 0x2E80)  # 中日韩等宽字符
    narrow = len(text) - wide
    return wide + (narrow + 3) // 4


def event_text(ev: dict[str, Any]) -> str:
    """提取事件里「计入 token 预算」的文本内容。"""
    etype = ev.get("type")
    if etype in (EVENT_MESSAGE, EVENT_REASONING, EVENT_TOOL_RESULT):
        return ev.get("content", "") or ""
    if etype == EVENT_TOOL_CALL:
        return json.dumps(ev.get("args", {}), ensure_ascii=False)
    return ""


class BudgetGuard:
    """预算守护：累计工具调用次数与 token 估算，判断是否超限。

    用于 lead_agent（``runs/worker.py::run_agent``）与内层 NarrationAgent
    （``narration/generate_narration.py``）的流式消费循环，防止 ReAct 死循环 /
    token 失控。这是纯代码硬约束，不依赖 LLM 自觉遵守 SKILL.md 的 stop_when 软约束。

    用法::

        guard = BudgetGuard(max_tool_calls=20, token_budget=32000, initial_tokens=len(prompt))
        for ev in events:
            guard.feed(ev)
        if guard.check():
            break  # 超限，中断流
    """

    def __init__(
        self,
        max_tool_calls: int,
        token_budget: int,
        initial_tokens: int = 0,
    ):
        self.max_tool_calls = max_tool_calls
        self.token_budget = token_budget
        self.tool_calls = 0
        self.tokens = initial_tokens
        self.exceeded = False

    def feed(self, event: dict[str, Any]) -> None:
        """喂入一个事件，累计 token 与工具调用次数。"""
        self.tokens += estimate_tokens(event_text(event))
        if event.get("type") == EVENT_TOOL_RESULT:
            self.tool_calls += 1

    def check(self) -> bool:
        """检查是否超限；超限则置 ``exceeded`` 标志并返回 True。"""
        if self.tool_calls >= self.max_tool_calls or self.tokens >= self.token_budget:
            self.exceeded = True
            return True
        return False
