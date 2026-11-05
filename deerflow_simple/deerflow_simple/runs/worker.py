"""worker —— 后台协程执行体，agent 消费用户任务的真正入口。

对应 DeerFlow 的 `runtime/runs/worker.py::run_agent` + `app/gateway/services.py::start_run`
里的后台派发部分。

精简后只保留协程管理骨架：

    准入（create_or_reject）→ 挂载 task → 同线程排队 → 启动屏障 → astream 消费 → 终态收尾

``submit_run`` 是非阻塞的：准入成功即返回 ``run_id``，agent 在后台协程里被
``agent.astream`` 逐 chunk 消费；``wait_run`` 负责阻塞等待结果。
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from langchain_core.messages import HumanMessage

from deerflow_simple.runs.manager import RunManager
from deerflow_simple.runs.schemas import RunRecord, RunStartOutcome, RunStatus
from deerflow_simple.tracing import build_run_metadata
from deerflow_simple.stream import (
    EVENT_DONE,
    EVENT_MESSAGE,
    SOURCE_LEAD,
    BudgetGuard,
    estimate_tokens,
    parse_stream_chunk,
    set_stream_emitter,
)

async def run_agent(
    manager: RunManager,
    record: RunRecord,
    *,
    graph: Any,
    message: str,
    config: dict[str, Any],
    novel_id: str | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
    max_tool_calls: int = 20,
    token_budget: int = 32000,
) -> None:
    """后台执行一次 agent run。

    与 DeerFlow 的 ``run_agent`` 对齐，按序执行：

    1. 等待同线程更早且正在收尾的 run（串行化）
    2. 通过启动屏障（pending → running，可被取消）
    3. 驱动 ``graph.astream(stream_mode="messages")`` 逐事件消费，直到结束或取消
    4. 终态收尾（success / error / interrupted）

    ``novel_id`` 是当前对话绑定的小说空间 id，写入 graph 输入 payload，供工具通过
    ``InjectedState("novel_id")`` 注入（不交给 LLM 决策）。

    ``on_event`` 是可选同步回调，收到每个结构化流式事件（message / reasoning /
    tool_call / tool_result）时调用（用于流式桥接）。同时通过 ``set_stream_emitter``
    绑定到当前 task，让内层工具（generate_narration）能透传事件回本回调。

    ``max_tool_calls`` / ``token_budget`` 是 lead_agent 层的预算守护（硬约束）：
    工具调用次数或 token 估算任一超限即中断流，防止 lead_agent 失控死循环。
    """
    run_id = record.run_id
    thread_id = record.thread_id
    # guard 在 try 外初始化为 None，确保 finally 阶段（含早期取消/异常路径）可安全引用
    guard: BudgetGuard | None = None

    try:
        # 收尾标志贯穿整个生命周期：run 一创建就处于 finalizing，保证同线程后续
        # run 在 wait_for_prior_finalizing 处排队，直到本 run 完全结束。
        # 注意必须放在 try 内——若 task 在运行前就被 cancel，第一个 await 点会
        # 抛 CancelledError，放在外面会逃逸导致状态无法落到 interrupted。
        await manager.set_finalizing(run_id, True)

        # 1. 同线程串行排队
        await manager.wait_for_prior_finalizing(
            thread_id,
            run_id,
            abort_event=record.abort_event,
        )

        # 2. 启动屏障
        outcome = await manager.try_start(run_id)
        if outcome is not RunStartOutcome.started:
            await manager.set_status(run_id, RunStatus.interrupted)
            return

        # 3. 驱动图执行（messages 模式：token 级 + 工具调用/返回事件）
        input_payload: dict[str, Any] = {"messages": [HumanMessage(content=message)]}
        if novel_id:
            input_payload["novel_id"] = novel_id

        # 绑定事件发射器到当前 task，内层工具通过 emit_event 透传。
        set_stream_emitter(on_event)

        result_text = ""
        pending_tool_calls: dict[int, dict[str, Any]] = {}
        guard = BudgetGuard(
            max_tool_calls=max_tool_calls,
            token_budget=token_budget,
            initial_tokens=estimate_tokens(message),
        )
        budget_exceeded = False
        stream = graph.astream(input_payload, config=config, stream_mode="messages")
        try:
            async for chunk in stream:
                if record.abort_event.is_set():
                    break
                message_part, _metadata = chunk
                events, is_tool_activity = parse_stream_chunk(
                    message_part, pending_tool_calls, SOURCE_LEAD
                )
                if is_tool_activity:
                    # 工具活动后，最终答案重新开始累计（工具调用前的文本是中间话）
                    result_text = ""
                for ev in events:
                    guard.feed(ev)
                    if ev["type"] == EVENT_MESSAGE:
                        result_text += ev["content"]
                    if on_event is not None:
                        on_event(ev)
                # 预算守护（硬约束）：工具调用次数或 token 任一超限即中断流
                if guard.check():
                    budget_exceeded = True
                    break
        finally:
            set_stream_emitter(None)
            close = getattr(stream, "aclose", None)
            if close is not None:
                try:
                    await close()
                except Exception:
                    pass

        # 4. 终态收尾
        if record.abort_event.is_set():
            if on_event is not None:
                on_event({"type": EVENT_DONE, "status": "interrupted", "source": SOURCE_LEAD})
            await manager.set_status(run_id, RunStatus.interrupted)
        else:
            # 预算耗尽且没写出正文：明确标注为 error，而非返回空结果
            if budget_exceeded and not result_text:
                await manager.set_status(
                    run_id,
                    RunStatus.error,
                    error=f"超出预算（工具调用 {guard.tool_calls} 次 / 估算 token {guard.tokens}），请缩小任务范围",
                )
                if on_event is not None:
                    on_event({"type": EVENT_DONE, "status": "error", "source": SOURCE_LEAD})
                return
            if on_event is not None:
                on_event({"type": EVENT_DONE, "status": "success", "result": result_text, "source": SOURCE_LEAD})
            await manager.set_status(run_id, RunStatus.success, result=result_text)
    except asyncio.CancelledError:
        # 取消统一映射为 interrupted：吞掉 CancelledError 让 task 正常结束，
        # 这样 wait_run 拿到的是「已中断」的 run 而不是抛 CancelledError。
        await manager.set_status(run_id, RunStatus.interrupted)
    except Exception as exc:  # noqa: BLE001 - 终态兜底，保证 run 不悬挂
        await manager.set_status(run_id, RunStatus.error, error=str(exc))
    finally:
        if guard is not None:
            await manager.set_token_usage(
                run_id, tokens=guard.tokens, tool_calls=guard.tool_calls
            )
        set_stream_emitter(None)
        await manager.set_finalizing(run_id, False)


async def submit_run(
    manager: RunManager,
    graph: Any,
    message: str,
    thread_id: str,
    *,
    multitask_strategy: str = "reject",
    session_id: str | None = None,
    recursion_limit: int = 9999,
    novel_id: str | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
    max_tool_calls: int = 20,
    token_budget: int = 32000,
) -> str:
    """准入并派发一个后台 run，返回 run_id（非阻塞）。

    对应 DeerFlow ``start_run`` 里 ``create_or_reject`` + ``asyncio.create_task``
    的部分：准入成功即返回，agent 在后台协程中被消费。

    ``reject`` 策略下若线程已有活跃 run 会抛 :class:`ConflictError`。

    ``novel_id`` 是当前对话绑定的小说空间 id，写入 graph state 供工具注入（不交给 LLM）。

    ``recursion_limit`` 是 LangGraph 层递归上限（安全阈值），注入到 ``graph.astream``
    的 RunnableConfig 顶层；agent 在「模型不再调用工具」时自然终止，此参数仅防死循环。

    ``on_event`` 是可选同步回调，收到每个结构化流式事件时调用（见 ``stream.py`` 事件协议）。

    ``max_tool_calls`` / ``token_budget`` 是 lead_agent 层预算守护，透传给 ``run_agent``。
    """
    record = await manager.create_or_reject(
        thread_id,
        multitask_strategy=multitask_strategy,
        session_id=session_id,
    )
    config: dict[str, Any] = {
        "configurable": {"thread_id": thread_id},
        "metadata": build_run_metadata(
            session_id=session_id,
            thread_id=thread_id,
            novel_id=novel_id,
            run_id=record.run_id,
        ),
        "tags": ["deerflow-simple", "narration"],
        "recursion_limit": recursion_limit,
    }
    worker = run_agent(
        manager,
        record,
        graph=graph,
        message=message,
        config=config,
        novel_id=novel_id,
        on_event=on_event,
        max_tool_calls=max_tool_calls,
        token_budget=token_budget,
    )
    record.task = asyncio.create_task(worker, name=f"deerflow-simple-run-{record.run_id}")
    return record.run_id


async def wait_run(
    manager: RunManager,
    run_id: str,
    *,
    timeout: float | None = None,
) -> str:
    """等待一个 run 完成，返回最终 AI 文本。

    - success：返回结果文本
    - error：抛出 :class:`RuntimeError`
    - interrupted：返回空串
    - ``timeout`` 超时只放弃等待（抛 ``TimeoutError``），不会取消 run。
    """
    record = manager.get(run_id)
    if record is None:
        raise KeyError(f"Unknown run {run_id}")

    if record.task is not None:
        if timeout is None:
            await record.task
        else:
            # shield 保证超时只放弃等待，后台 run 继续跑完。
            await asyncio.wait_for(asyncio.shield(record.task), timeout=timeout)

    if record.status == RunStatus.success:
        return record.result or ""
    if record.error:
        raise RuntimeError(record.error)
    return ""
