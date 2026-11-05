"""会话模块 —— 会话（session）+ 线程（thread）的持久化元数据。

一个 session 包含 1..N 个 thread；thread 是 LangGraph checkpointer 的执行 key。
session_id / thread_id 均用 LangSmith UUIDv7 生成，并打进 LangSmith 的 metadata
用于追踪归组（session 视图 + thread 视图）。
"""

from deerflow_simple.sessions.manager import (
    SessionManager,
    SessionNotFoundError,
    ThreadNotFoundError,
)
from deerflow_simple.sessions.models import Session, Thread, new_id
from deerflow_simple.sessions.store import SessionStore

__all__ = [
    "Session",
    "Thread",
    "new_id",
    "SessionStore",
    "SessionManager",
    "SessionNotFoundError",
    "ThreadNotFoundError",
]
