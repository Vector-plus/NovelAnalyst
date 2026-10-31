"""SummarizationMiddleware —— 接近 token 上限时自动摘要压缩。

对应 DeerFlow 的 `summarization_middleware.py`（它继承 LangChain 内置的
`SummarizationMiddleware`；精简版自写一个更直观的实现）。

职责：在 `before_model` 检查消息总 token 是否超过阈值，超过则把旧消息交给 LLM
压缩成一段摘要，只保留最近 N 条消息。摘要写入 `summary_text` 通道（而不是作为一条
普通消息），由 DurableContextMiddleware 投影回后续请求。

核心机制：用 `RemoveMessage(id=REMOVE_ALL_MESSAGES)` 清空消息通道，再写入保留的
尾部消息——这就是"compaction"。
"""

from __future__ import annotations

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import RemoveMessage, get_buffer_string
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.runtime import Runtime


def _approx_tokens(messages: list) -> int:
    """粗略 token 估算：每 4 个字符约 1 个 token（学习项目，够用）。"""
    total = 0
    for m in messages:
        content = m.content
        total += len(content) if isinstance(content, str) else len(str(content))
    return total // 4


class SummarizationMiddleware(AgentMiddleware):
    def __init__(self, config, model):
        super().__init__()
        self._config = config
        self._model = model

    def _summarize(self, to_summarize: list, previous: str | None) -> str | None:
        text = get_buffer_string(to_summarize)
        prompt = (
            "请把下面这段对话压缩成简洁的摘要，保留关键事实、用户偏好和未完成的任务。\n\n"
        )
        if previous:
            prompt += f"已有的摘要：\n{previous}\n\n"
        prompt += f"新对话：\n{text}"
        try:
            resp = self._model.invoke(prompt)
            return resp.content if isinstance(resp.content, str) else str(resp.content)
        except Exception:
            # 摘要失败不影响主流程，下次再试
            return None

    def before_model(self, state, runtime: Runtime) -> dict | None:
        messages = list(state.get("messages", []))
        if not self._config.summarization_enabled:
            return None
        if _approx_tokens(messages) < self._config.summarization_trigger_tokens:
            return None

        keep_n = self._config.summarization_keep_messages
        if len(messages) <= keep_n:
            return None
        to_summarize = messages[:-keep_n]
        keep = messages[-keep_n:]

        previous = state.get("summary_text")
        summary = self._summarize(to_summarize, previous)
        if summary is None:
            return None

        return {
            "messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *keep],
            "summary_text": summary,
        }
