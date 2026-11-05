"""会话 + 线程的 HTTP API（纯后端，无 LLM 参与）。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from deerflow_simple.sessions.manager import (
    SessionManager,
    SessionNotFoundError,
)
from deerflow_simple.sessions.models import Session, Thread
from deerflow_simple.sessions.schemas import (
    SessionCreateRequest,
    SessionCreateResponse,
    SessionDetailResponse,
    SessionResponse,
    ThreadCreateRequest,
    ThreadResponse,
)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def _get_manager(request: Request) -> SessionManager:
    return request.app.state.session_manager


def _to_session_response(session: Session) -> SessionResponse:
    return SessionResponse(
        session_id=session.session_id,
        novel_id=session.novel_id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def _to_thread_response(thread: Thread) -> ThreadResponse:
    return ThreadResponse(
        thread_id=thread.thread_id,
        session_id=thread.session_id,
        title=thread.title,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
    )


@router.post("", response_model=SessionCreateResponse, status_code=201)
async def create_session(
    body: SessionCreateRequest, request: Request
) -> SessionCreateResponse:
    """创建会话，并自动开一个默认线程（开箱即用，直接返回 thread_id）。"""
    manager = _get_manager(request)
    session, thread = manager.create_session(body.novel_id, body.title)
    return SessionCreateResponse(
        session_id=session.session_id,
        thread_id=thread.thread_id,
        novel_id=session.novel_id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


@router.get("", response_model=list[SessionResponse])
async def list_sessions(request: Request) -> list[SessionResponse]:
    """列出全部会话。"""
    manager = _get_manager(request)
    return [_to_session_response(s) for s in manager.list_sessions()]


@router.get("/{session_id}", response_model=SessionDetailResponse)
async def get_session(session_id: str, request: Request) -> SessionDetailResponse:
    """查询会话详情（含线程列表）。"""
    manager = _get_manager(request)
    try:
        session = manager.get_session(session_id)
        threads = manager.list_threads(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return SessionDetailResponse(
        session_id=session.session_id,
        novel_id=session.novel_id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
        threads=[_to_thread_response(t) for t in threads],
    )


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: str, request: Request) -> None:
    """删除会话（级联删除其下所有线程的 checkpoint）。"""
    manager = _get_manager(request)
    try:
        await manager.delete_session(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/{session_id}/threads", response_model=ThreadResponse, status_code=201
)
async def create_thread(
    session_id: str, body: ThreadCreateRequest, request: Request
) -> ThreadResponse:
    """在会话下新建线程（分支 / 新话题）。"""
    manager = _get_manager(request)
    try:
        thread = manager.create_thread(session_id, body.title)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_thread_response(thread)
