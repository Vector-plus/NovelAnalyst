"""run 相关 HTTP API —— 创建、等待、流式、查询、取消。

对应 DeerFlow 的 `app/gateway/routers/runs.py` + `thread_runs.py` 的 run 部分，
去掉 authz / store / event store / stream bridge 等企业级组件，只保留
worker 协程管理（`submit_run` / `wait_run` / `RunManager`）对外的 HTTP 边界。
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from langchain_core.messages import AIMessage, HumanMessage

from deerflow_simple.app.schemas import RunCreateRequest, RunResponse
from deerflow_simple.runs import ConflictError, RunManager, submit_run, wait_run
from deerflow_simple.stream import EVENT_DONE

router = APIRouter(prefix="/api", tags=["runs"])


def _get_graph(request: Request):
    """从 app.state 取共享的编译后 agent graph。"""
    return request.app.state.graph


def _get_manager(request: Request) -> RunManager:
    """从 app.state 取共享的 RunManager。"""
    return request.app.state.run_manager


def _get_config(request: Request):
    """从 app.state 取共享的 SimpleConfig（读取预算等配置）。"""
    return request.app.state.config


def _record_to_response(record) -> RunResponse:
    return RunResponse(
        run_id=record.run_id,
        thread_id=record.thread_id,
        session_id=record.session_id,
        status=record.status.value,
        multitask_strategy=record.multitask_strategy,
        error=record.error,
        result=record.result,
        tokens=record.tokens,
        tool_calls=record.tool_calls,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _sse(event: str, data: dict) -> str:
    """把一个事件编码为一行 SSE data。"""
    payload = json.dumps({"event": event, "data": data}, ensure_ascii=False)
    return f"data: {payload}\n\n"


# ---------------------------------------------------------------------------
# Stateless run 端点（不要求预先存在 thread）
# ---------------------------------------------------------------------------


@router.post("/runs", response_model=RunResponse)
async def create_run(body: RunCreateRequest, request: Request) -> RunResponse:
    """创建后台 run（立即返回，不阻塞）。"""
    manager = _get_manager(request)
    graph = _get_graph(request)
    config = _get_config(request)
    try:
        run_id = await submit_run(
            manager,
            graph,
            body.message,
            body.thread_id,
            multitask_strategy=body.multitask_strategy,
            novel_id=body.novel_id,
            session_id=body.session_id,
            max_tool_calls=config.agent_max_tool_calls,
            token_budget=config.agent_token_budget,
        )
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _record_to_response(manager.get(run_id))


@router.post("/runs/wait", response_model=dict)
async def wait_run_endpoint(body: RunCreateRequest, request: Request) -> dict:
    """创建 run 并阻塞等待完成，返回最终状态与结果。"""
    manager = _get_manager(request)
    graph = _get_graph(request)
    config = _get_config(request)
    try:
        run_id = await submit_run(
            manager,
            graph,
            body.message,
            body.thread_id,
            multitask_strategy=body.multitask_strategy,
            novel_id=body.novel_id,
            session_id=body.session_id,
            max_tool_calls=config.agent_max_tool_calls,
            token_budget=config.agent_token_budget,
        )
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    try:
        result = await wait_run(manager, run_id)
    except RuntimeError as exc:
        record = manager.get(run_id)
        return {"status": record.status.value, "error": str(exc)}

    record = manager.get(run_id)
    return {
        "run_id": run_id,
        "status": record.status.value,
        "result": result,
        "error": record.error,
    }


@router.post("/runs/stream")
async def stream_run(body: RunCreateRequest, request: Request) -> StreamingResponse:
    """创建 run 并逐事件通过 SSE 流式返回。

    事件序列：``run.created`` → 多条结构化事件（``message`` / ``reasoning`` /
    ``tool_call`` / ``tool_result``）→ ``run.finished`` → ``[DONE]``。

    结构化事件由 ``stream.py`` 的事件协议定义，每个事件都带 ``source`` 字段
    （``lead`` 或 ``narration``）区分事件来自 lead_agent 还是内层 NarrationAgent。
    """
    manager = _get_manager(request)
    graph = _get_graph(request)
    config = _get_config(request)
    queue: asyncio.Queue = asyncio.Queue()

    def on_event(event: dict) -> None:
        queue.put_nowait(event)

    try:
        run_id = await submit_run(
            manager,
            graph,
            body.message,
            body.thread_id,
            multitask_strategy=body.multitask_strategy,
            novel_id=body.novel_id,
            session_id=body.session_id,
            on_event=on_event,
            max_tool_calls=config.agent_max_tool_calls,
            token_budget=config.agent_token_budget,
        )
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    async def _waiter() -> None:
        # 后台等待 run 结束，结束后向队列投递 None 作为终止标记
        try:
            await wait_run(manager, run_id)
        except Exception:
            pass
        finally:
            queue.put_nowait(None)

    asyncio.create_task(_waiter())

    async def event_generator():
        yield _sse("run.created", {"run_id": run_id, "thread_id": body.thread_id})
        while True:
            event = await queue.get()
            if event is None:
                break
            # done 事件已在 worker 里发出，但最终状态以 RunManager 为准，
            # 这里把结构化事件原样透传（message/reasoning/tool_call/tool_result）。
            if event.get("type") == EVENT_DONE:
                # 跳过 worker 发出的 done（终态统一在 run.finished 里输出）
                continue
            yield _sse("event", event)

        record = manager.get(run_id)
        status = record.status.value if record is not None else "error"
        yield _sse(
            "run.finished",
            {
                "run_id": run_id,
                "status": status,
                "result": record.result if record is not None else None,
                "error": record.error if record is not None else None,
                "tokens": record.tokens if record is not None else 0,
                "tool_calls": record.tool_calls if record is not None else 0,
            },
        )
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Thread-scoped run 端点（带 thread_id 路径参数）
# ---------------------------------------------------------------------------


@router.get("/threads/{thread_id}/runs", response_model=list[RunResponse])
async def list_runs(thread_id: str, request: Request) -> list[RunResponse]:
    """列出某线程的全部 run（按创建顺序）。"""
    manager = _get_manager(request)
    return [_record_to_response(r) for r in manager.list_by_thread(thread_id)]


@router.get("/threads/{thread_id}/runs/{run_id}", response_model=RunResponse)
async def get_run(thread_id: str, run_id: str, request: Request) -> RunResponse:
    """查询单个 run 详情。"""
    manager = _get_manager(request)
    record = manager.get(run_id)
    if record is None or record.thread_id != thread_id:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return _record_to_response(record)


@router.post("/threads/{thread_id}/runs/{run_id}/cancel", response_model=RunResponse)
async def cancel_run(thread_id: str, run_id: str, request: Request) -> RunResponse:
    """取消一个 pending/running 的 run。"""
    manager = _get_manager(request)
    record = manager.get(run_id)
    if record is None or record.thread_id != thread_id:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    cancelled = manager.cancel(run_id)
    if not cancelled:
        raise HTTPException(
            status_code=409,
            detail=f"Run {run_id} is not cancellable (status: {record.status.value})",
        )
    return _record_to_response(record)


@router.get("/threads/{thread_id}/history", response_model=list[dict])
async def get_thread_history(thread_id: str, request: Request) -> list[dict]:
    """读取某线程的历史消息（仅 human/ai 两类，工具调用细节不回放）。"""
    checkpointer = request.app.state.checkpointer
    if checkpointer is None:
        return []
    try:
        state = await checkpointer.aget_tuple(
            {"configurable": {"thread_id": thread_id}}
        )
    except Exception:  # noqa: BLE001 - 读取失败返回空历史
        return []
    if state is None or state.checkpoint is None:
        return []
    messages = state.checkpoint.get("channel_values", {}).get("messages", [])
    history: list[dict] = []
    for m in messages:
        if isinstance(m, HumanMessage):
            if isinstance(m.content, str) and m.content:
                history.append({"role": "human", "content": m.content})
        elif isinstance(m, AIMessage):
            if isinstance(m.content, str) and m.content:
                history.append({"role": "ai", "content": m.content})
    return history