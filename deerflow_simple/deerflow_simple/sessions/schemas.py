"""会话 API 的请求 / 响应模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SessionCreateRequest(BaseModel):
    """创建会话的请求体。"""

    novel_id: str | None = Field(default=None, description="绑定的小说空间 id")
    title: str = Field(default="", max_length=200, description="会话标题")


class ThreadCreateRequest(BaseModel):
    """在会话下新建线程的请求体。"""

    title: str = Field(default="", max_length=200, description="线程标题")


class SessionResponse(BaseModel):
    """会话响应体。"""

    session_id: str
    novel_id: str | None = None
    title: str = ""
    created_at: str
    updated_at: str


class ThreadResponse(BaseModel):
    """线程响应体。"""

    thread_id: str
    session_id: str
    title: str = ""
    created_at: str
    updated_at: str


class SessionDetailResponse(SessionResponse):
    """会话详情（含线程列表）。"""

    threads: list[ThreadResponse] = Field(default_factory=list)


class SessionCreateResponse(SessionResponse):
    """创建会话的响应：同时返回默认线程 id，便于直接开始对话。"""

    thread_id: str
