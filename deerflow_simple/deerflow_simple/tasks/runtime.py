"""长任务后台协程 —— 驱动编译后的 graph 执行，并把执行过程转成统一事件流。

对应设计文档《03-核心图设计_索引生成.md》§4 的中断恢复 + §6 的异步执行。

与 ``runs/worker.py`` 的差异（关键边界）：
- runs 是「对话 run」，用 ``stream_mode="messages"`` 逐 token 透传 lead_agent 事件；
- 这里是「长任务」，用 ``stream_mode=["updates", "messages"]``：
  - ``updates`` 给节点边界 → 发射 ``node`` 事件（宏观进度）+ 推进 task.phase；
  - ``messages`` 给节点内 ReAct 细节 → 复用 ``parse_stream_chunk`` 透传
    tool_call / tool_result / message / reasoning（微观详情）。

事件不通过 contextvar 桥（跨 task 会失效），而是直接放入 ``record.event_queue``，
由 SSE 端点从队列消费（见 ``app/routers/tasks.py``）。
"""

from __future__ import annotations

import asyncio
from typing import Any

from deerflow_simple.stream import (
    EVENT_DONE,
    EVENT_NODE,
    SOURCE_INDEX,
    parse_stream_chunk,
    set_stream_emitter,
)
from deerflow_simple.tasks.schemas import TaskRecord, TaskStatus


async def run_task(
    record: TaskRecord,
    *,
    graph: Any,
    input_payload: dict[str, Any] | None,
    config: dict[str, Any],
    manager: Any,
) -> None:
    """后台执行一次长任务，直到终态或被 interrupt 暂停。

    Args:
        record: 任务记录（含 event_queue / abort_event）。
        graph: 编译好的 StateGraph（带 checkpointer）。
        input_payload: graph 输入；resume 时为 ``None``（从 checkpoint 继续）。
        config: RunnableConfig（``configurable.thread_id`` = task_id）。
        manager: TaskManager（供 set_status / set_phase / emit 回调）。
    """
    task_id = record.task_id

    async def _emit(event: dict[str, Any]) -> None:
        await manager.emit(task_id, event)

    # 节点内部 agent 的微观事件（tool_call / tool_result / message / reasoning）通过
    # contextvar 桥（stream.emit_event）透传。这里绑定一个同步 sink，把事件直接放入
    # 本任务的 event_queue。节点与 run_task 在同一 asyncio task 内（graph.astream 的
    # await 链），contextvar 自动传播，无需在节点间显式传 emitter。
    def _index_event_sink(event: dict[str, Any]) -> None:
        if record.event_queue is not None:
            record.event_queue.put_nowait(event)

    try:
        await manager.set_status(task_id, TaskStatus.running)

        # 绑定事件桥（本 task 内生效，节点内部的 emit_event 会命中此 sink）
        set_stream_emitter(_index_event_sink)

        pending_tool_calls: dict[int, dict[str, Any]] = {}
        stream = graph.astream(
            input_payload,
            config=config,
            stream_mode=["updates", "messages"],
        )
        try:
            async for mode, chunk in stream:
                if record.abort_event.is_set():
                    await manager.set_status(task_id, TaskStatus.cancelled)
                    await _emit({"type": EVENT_DONE, "status": "cancelled", "source": SOURCE_INDEX})
                    return

                if mode == "updates":
                    # updates：{node_name: update_dict}，一个节点完成后返回。
                    # 跳过 LangGraph 内部键（如 __interrupt__）与内部路由节点（entry），
                    # 只把有意义的阶段节点（skeleton/prescan/review_plan）暴露给前端。
                    for node_name in chunk.keys():
                        if str(node_name).startswith("__") or str(node_name) == "entry":
                            continue
                        await manager.set_phase(task_id, node_name)
                        await _emit(
                            {
                                "type": EVENT_NODE,
                                "node": node_name,
                                "status": "exit",
                                "source": SOURCE_INDEX,
                            }
                        )
                elif mode == "messages":
                    message_part, _metadata = chunk
                    events, _ = parse_stream_chunk(
                        message_part, pending_tool_calls, SOURCE_INDEX
                    )
                    for ev in events:
                        await _emit(ev)
        finally:
            close = getattr(stream, "aclose", None)
            if close is not None:
                try:
                    await close()
                except Exception:
                    pass

        # 消费结束后判断终态：被 interrupt 暂停 vs 正常结束。
        # LangGraph 在 interrupt_before 中断后，state.next 保留待执行节点；
        # 正常结束后 state.next 为空。据此区分 paused / done。
        state = graph.get_state(config)
        pending_next = getattr(state, "next", None)
        if pending_next:
            # 取待执行节点名作为「等待人工」的阶段：interrupt_before 挂起在
            # review_plan / review_issues 前，phase 应显示待执行节点而非上一个
            # 已完成的节点（如 prescan / audit）。
            if isinstance(pending_next, (tuple, list)) and pending_next:
                pending_node = str(pending_next[0])
            else:
                # 防御性兜底：interrupt_before 中断后 next 理论上必非空且为
                # tuple/list，此分支不会命中；仅保证 pending_node 有默认值。
                pending_node = "review_plan"
            await manager.set_phase(task_id, pending_node)
            await manager.set_status(task_id, TaskStatus.paused)
            await _emit(
                {
                    "type": EVENT_NODE,
                    "node": pending_node,
                    "status": "paused",
                    "source": SOURCE_INDEX,
                }
            )
        else:
            # 正常结束：phase 应反映最终阶段（state.phase），而非停留在最后退出的
            # 节点名。例：audit 无 critical 时 state.phase="done"，但最后退出的节点
            # 是 "audit"，若不覆盖会显示成 status=done 而 phase=audit 的矛盾组合。
            # 注意：phase 在「运行中」由 updates 事件用节点名推进（见上方），语义
            # 是「当前/刚完成的阶段」；到终态这里要切回「最终阶段」（done）。
            final_phase = (getattr(state, "values", None) or {}).get("phase", "done")
            await manager.set_phase(task_id, final_phase)
            await manager.set_status(task_id, TaskStatus.done)
            await _emit({"type": EVENT_DONE, "status": "done", "source": SOURCE_INDEX})
    except asyncio.CancelledError:
        await manager.set_status(task_id, TaskStatus.cancelled)
    except Exception as exc:  # noqa: BLE001 - 终态兜底，保证任务不悬挂
        await manager.set_status(task_id, TaskStatus.failed, error=str(exc))
        await _emit(
            {"type": EVENT_DONE, "status": "failed", "error": str(exc), "source": SOURCE_INDEX}
        )
    finally:
        # 解绑事件桥（避免 contextvar 残留影响同一 task 复用场景）。
        set_stream_emitter(None)
        # 终态哨兵：SSE 端点消费到 None 即结束流。
        if record.event_queue is not None:
            record.event_queue.put_nowait(None)
