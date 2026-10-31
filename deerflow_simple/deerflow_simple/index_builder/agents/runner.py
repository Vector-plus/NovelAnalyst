"""index_builder 子 agent 的统一流式执行 helper。

问题背景：节点此前用 ``agent.ainvoke(...)`` 一次性调用 ``create_agent`` 返回的
agent，整个执行过程（工具调用 / 思考 / 中间 message）被吞掉，只返回最终 result。
外层 ``runtime.run_task`` 的 ``graph.astream(stream_mode=["updates","messages"])``
只能捕获节点边界（updates），捕获不到节点内部 agent 的微观事件。

解决方案（对齐 narration/generate_narration.py 已验证的模式）：
- 节点改用 ``agent.astream(stream_mode="messages")`` 流式消费；
- 每个 chunk 用 ``parse_stream_chunk`` 解析成事件；
- ``emit_event(ev)`` 通过 contextvar 桥透传回 task 的 event_queue（runtime.run_task
  在执行前 ``set_stream_emitter`` 绑定 emitter；节点与 run_task 在同一 asyncio task
  内，contextvar 自动传播）。

本 helper 返回「最终文本」（index_builder 子 agent 输出的是结构化 JSON 文本），
节点用各自的 ``_parse_json`` 解析。与 narration 的差异：narration 累计的是解说稿
正文，这里累计的是 JSON 输出；二者都靠 ``is_tool_activity`` 重置「工具活动前的
中间话」，只保留工具活动后的最终答案。
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from deerflow_simple.config import SimpleConfig
from deerflow_simple.stream import (
    EVENT_MESSAGE,
    SOURCE_INDEX,
    BudgetGuard,
    emit_event,
    estimate_tokens,
    parse_stream_chunk,
)


async def run_agent_streaming(
    agent,
    prompt: str,
    config: SimpleConfig,
) -> str:
    """流式执行一个 index_builder 子 agent，透传事件，返回最终文本。

    Args:
        agent: ``create_agent`` 返回的 CompiledStateGraph。
        prompt: User Prompt（system_prompt 已在 agent 构建时注入）。
        config: SimpleConfig（取 index_max_tool_calls / index_token_budget /
            recursion_limit）。

    Returns:
        最终文本（index_builder 子 agent 输出的 JSON 字符串），由调用方 parse_json。

    降级策略（D11）：reasoning 模型（DeepSeek v4.1 flash）流式输出时，会先输出大量
    「思考」（空 content chunk）+ 工具调用，最后才输出正式 JSON。服务抖动时，流可能在
    「输出正式 JSON 前」被截断，导致 content 全空。此时降级用 ``agent.ainvoke``
    （非流式、等完整执行）重试，从 ``result["messages"][-1].content`` 取最终结果，
    绕过流式 chunk 截断问题。降级路径不透传微观事件（可接受，属兜底）。
    """
    final_text = ""
    pending_tool_calls: dict[int, dict] = {}
    budget_exceeded = False
    guard = BudgetGuard(
        max_tool_calls=config.index_max_tool_calls,
        token_budget=config.index_token_budget,
        initial_tokens=estimate_tokens(prompt),
    )

    stream = agent.astream(
        {"messages": [HumanMessage(content=prompt)]},
        config={"recursion_limit": config.recursion_limit},
        stream_mode="messages",
    )
    try:
        async for chunk in stream:
            message_part, _metadata = chunk
            events, is_tool_activity = parse_stream_chunk(
                message_part, pending_tool_calls, SOURCE_INDEX
            )
            if is_tool_activity:
                # 工具活动前的文本是「中间话」（如「我先读一下文件」），不是最终 JSON，
                # 重置后只累计工具活动结束后的最终答案。
                final_text = ""
            for ev in events:
                guard.feed(ev)
                if ev["type"] == EVENT_MESSAGE:
                    final_text += ev["content"]
                emit_event(ev)
            if guard.check():
                budget_exceeded = True
                break
    finally:
        close = getattr(stream, "aclose", None)
        if close is not None:
            try:
                await close()
            except Exception:
                pass

    if final_text.strip():
        return final_text

    # 降级：流式空输出（reasoning 模型流被截断）→ 用 ainvoke 非流式重试一次。
    # ainvoke 等待 agent 完整执行结束，直接取最终消息 content，更稳定。
    if not budget_exceeded:
        try:
            result = await agent.ainvoke(
                {"messages": [HumanMessage(content=prompt)]},
                config={"recursion_limit": config.recursion_limit},
            )
            text = result["messages"][-1].content
            if isinstance(text, str) and text.strip():
                return text
        except Exception:
            # 降级也失败则继续走下方抛错，保留明确错误信息。
            pass

    # 空输出防御：agent 正常结束但没产出任何文本（LLM 偶发返回空 / 内容全被工具活动
    # 重置 / 流被截断）。若直接返回空串，上游 ``_parse_json("")`` 会抛误导性的
    # 「Expecting value: line 1 column 1 (char 0)」，掩盖真实根因。这里提前抛明确错误，
    # 便于上游（prescan/deepread/audit）的重试逻辑捕获并区分「预算超限」与「空输出」。
    if budget_exceeded:
        raise RuntimeError("agent 执行超出预算（工具调用/ token 超限）且未产出文本")
    raise RuntimeError(
        "agent 流式执行结束且 ainvoke 降级重试后仍未产出任何文本（LLM 可能返回空内容）"
    )
