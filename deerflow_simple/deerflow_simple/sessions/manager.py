"""SessionManager —— 会话 + 线程的生命周期协调。

负责把「业务元数据（sessions/threads 表）」与「LangGraph checkpoint
（checkpointer，key=thread_id）」串联起来：

- 创建 session 时自动开一个默认 thread（开箱即用）。
- 删除 session 时级联删除其下所有 thread 的 checkpoint（清理对话历史）。

``checkpointer`` 仅在删除级联时需要，其余 CRUD 都走 SessionStore。
"""

from __future__ import annotations

from typing import Any

from deerflow_simple.sessions.models import Session, Thread
from deerflow_simple.sessions.store import SessionStore


class SessionNotFoundError(Exception):
    """会话不存在。"""


class ThreadNotFoundError(Exception):
    """线程不存在。"""


class SessionManager:
    """会话 + 线程元数据管理器。"""

    def __init__(self, store: SessionStore, checkpointer: Any = None):
        self._store = store
        self._checkpointer = checkpointer

    # ------------------------------------------------------------------
    # Session
    # ------------------------------------------------------------------
    def create_session(
        self, novel_id: str | None = None, title: str = ""
    ) -> tuple[Session, Thread]:
        """创建会话并自动开一个默认 thread，返回 (session, default_thread)。"""
        session = Session(novel_id=novel_id, title=title)
        self._store.insert_session(session)
        thread = Thread(session_id=session.session_id, title="默认对话")
        self._store.insert_thread(thread)
        return session, thread

    def get_session(self, session_id: str) -> Session:
        session = self._store.get_session(session_id)
        if session is None:
            raise SessionNotFoundError(f"Session {session_id} not found")
        return session

    def list_sessions(self) -> list[Session]:
        return self._store.list_sessions()

    async def delete_session(self, session_id: str) -> None:
        """删除会话，级联删除其下所有线程的 checkpoint。"""
        if self._store.get_session(session_id) is None:
            raise SessionNotFoundError(f"Session {session_id} not found")

        threads = self._store.list_threads(session_id)
        # 先删 checkpoint（若有 checkpointer），再删元数据
        for t in threads:
            await self._delete_checkpoint(t.thread_id)
        self._store.delete_session(session_id)

    # ------------------------------------------------------------------
    # Thread
    # ------------------------------------------------------------------
    def create_thread(self, session_id: str, title: str = "") -> Thread:
        if self._store.get_session(session_id) is None:
            raise SessionNotFoundError(f"Session {session_id} not found")
        thread = Thread(session_id=session_id, title=title)
        self._store.insert_thread(thread)
        return thread

    def list_threads(self, session_id: str) -> list[Thread]:
        if self._store.get_session(session_id) is None:
            raise SessionNotFoundError(f"Session {session_id} not found")
        return self._store.list_threads(session_id)

    # ------------------------------------------------------------------
    # checkpoint 级联
    # ------------------------------------------------------------------
    async def _delete_checkpoint(self, thread_id: str) -> None:
        """删除一个 thread 的所有 checkpoint（清理对话历史）。

        删除失败不阻断会话元数据删除（尽力而为），避免因 checkpoint 后端
        异常导致会话删除卡死。
        """
        if self._checkpointer is None:
            return
        try:
            await self._checkpointer.adelete_thread(thread_id)
        except Exception:  # noqa: BLE001 - 尽力而为
            pass
