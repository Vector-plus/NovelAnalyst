"""长任务（索引生成等）HTTP API —— 创建、查询、SSE 订阅、暂停恢复、取消。

对应设计文档《03-核心图设计_索引生成.md》§4.5 / §6 的对外接口，但升级为通用
长任务运行时（决策 B1：一期只做 REST API，不挂 lead_agent 工具）。

与 ``runs.py`` 的差异：runs 是「POST /runs/stream 同时创建并订阅」（对话 run）；
这里是「POST /tasks 创建（返回 task_id）→ POST /tasks/{id}/stream 稍后订阅」
（长任务，任务可能已跑了很久，前端才来订阅进度）。
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from deerflow_simple.app.schemas import (
    TaskCreateRequest,
    TaskResumeRequest,
    TaskResponse,
)
from deerflow_simple.index_builder import build_initial_state
from deerflow_simple.spaces.manager import SpaceManager, SpaceNotFoundError
from deerflow_simple.tasks import TaskManager, TaskRecord, TaskStatus

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _get_manager(request: Request) -> TaskManager:
    return request.app.state.task_manager


def _get_config(request: Request):
    return request.app.state.config


def _get_space_manager(request: Request) -> SpaceManager:
    return request.app.state.space_manager


def _to_response(record: TaskRecord) -> TaskResponse:
    return TaskResponse(
        task_id=record.task_id,
        novel_id=record.novel_id,
        kind=record.kind,
        status=record.status.value,
        phase=record.phase,
        error=record.error,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _sse(event: str, data: dict) -> str:
    """把一个事件编码为一行 SSE data。"""
    payload = json.dumps({"event": event, "data": data}, ensure_ascii=False)
    return f"data: {payload}\n\n"


# ---------------------------------------------------------------------------
# 创建 / 查询
# ---------------------------------------------------------------------------

@router.post("", response_model=TaskResponse, status_code=202)
async def create_task(body: TaskCreateRequest, request: Request) -> TaskResponse:
    """创建索引生成任务（立即返回 task_id，后台异步执行）。"""
    manager = _get_manager(request)
    config = _get_config(request)

    # 校验小说空间存在
    try:
        _get_space_manager(request).get_space(body.novel_id)
    except SpaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    input_payload = build_initial_state(
        config, body.novel_id, body.source_version, body.build_mode
    )
    task_id = await manager.start(body.novel_id, input_payload, kind=body.kind)
    record = manager.get(task_id)
    return _to_response(record)


@router.get("", response_model=list[TaskResponse])
async def list_tasks(request: Request, novel_id: str | None = None) -> list[TaskResponse]:
    """列出长任务（可按 novel_id 过滤）。"""
    manager = _get_manager(request)
    return [_to_response(r) for r in manager.list(novel_id)]


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str, request: Request) -> TaskResponse:
    """查询单个任务详情（status / phase / error）。"""
    manager = _get_manager(request)
    record = manager.get(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
    return _to_response(record)


# ---------------------------------------------------------------------------
# SSE 订阅（宏观进度 + 微观执行详情）
# ---------------------------------------------------------------------------

@router.post("/{task_id}/stream")
async def stream_task(task_id: str, request: Request) -> StreamingResponse:
    """订阅任务的事件流（SSE）。

    事件序列：``task.status``（当前快照）→ 多条结构化事件（``node`` / ``tool_call`` /
    ``tool_result`` / ``message`` / ``reasoning``，均带 ``source=index``）→ ``[DONE]``。
    事件来自后台协程写入的任务事件队列；任务终态时队列放入 None 哨兵，流结束。
    """
    manager = _get_manager(request)
    record = manager.get(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")

    queue = manager.get_event_queue(task_id)

    async def event_generator():
        yield _sse(
            "task.status",
            {"task_id": task_id, "status": record.status.value, "phase": record.phase},
        )
        if queue is None:
            yield "data: [DONE]\n\n"
            return
        while True:
            event = await queue.get()
            if event is None:
                break
            yield _sse("event", event)

        final = manager.get(task_id)
        yield _sse(
            "task.finished",
            {
                "task_id": task_id,
                "status": final.status.value if final else "failed",
                "phase": final.phase if final else "",
                "error": final.error if final else None,
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
# 暂停恢复 / 取消
# ---------------------------------------------------------------------------

@router.post("/{task_id}/resume", response_model=TaskResponse)
async def resume_task(
    task_id: str, body: TaskResumeRequest, request: Request
) -> TaskResponse:
    """恢复一个 paused 任务（可携带 Human-in-Loop 决策）。

    两个 interrupt 点的 paused 任务均可恢复，决策按 interrupt 点区分：
    - ``review_plan``：``{"decision": "approve"}`` / ``{"decision": "reject"}``
    - ``review_issues``：``{"decision": "fixed"}`` / ``{"decision": "skip"}`` /
      ``{"decision": "stop"}``
    cancelled / failed / done 均不可恢复，需重新创建任务。
    """
    manager = _get_manager(request)
    record = manager.get(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
    if record.status != TaskStatus.paused:
        raise HTTPException(
            status_code=409,
            detail=(
                f"任务 {task_id} 不是 paused 状态（当前: {record.status.value}）。"
                "只有等待人工审核（review_plan / review_issues）而暂停的任务才能 resume；"
                "cancelled/failed/done 任务请重新创建任务（POST /api/tasks）。"
            ),
        )
    try:
        await manager.resume(task_id, body.decision)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_response(manager.get(task_id))


@router.post("/{task_id}/cancel", response_model=TaskResponse)
async def cancel_task(task_id: str, request: Request) -> TaskResponse:
    """取消一个活跃任务。"""
    manager = _get_manager(request)
    record = manager.get(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
    cancelled = await manager.cancel(task_id)
    if not cancelled:
        raise HTTPException(
            status_code=409,
            detail=f"任务 {task_id} 不可取消（当前: {record.status.value}）",
        )
    return _to_response(manager.get(task_id))
