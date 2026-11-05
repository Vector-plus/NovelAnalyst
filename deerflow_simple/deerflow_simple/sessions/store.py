"""SessionStore —— 会话元数据的 SQLite 存储（标准库，无 ORM）。

与 ``spaces/store.py`` 同构：两张表 ``sessions`` / ``threads``，按 id 精确查 /
按 session 列 thread / 全量列表。会话是对话的持久化元数据层，checkpoint 另由
LangGraph 的 SqliteSaver 管理（thread_id 为 key）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from deerflow_simple.sessions.models import Session, Thread

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    novel_id TEXT,
    title TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS threads (
    thread_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_threads_session ON threads (session_id);
"""


class SessionStore:
    """会话 + 线程元数据的 SQLite 存取层。"""

    def __init__(self, db_path: str | Path):
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------
    # 行转换
    # ------------------------------------------------------------------
    @staticmethod
    def _row_to_session(row: sqlite3.Row) -> Session:
        return Session(
            session_id=row["session_id"],
            novel_id=row["novel_id"],
            title=row["title"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_thread(row: sqlite3.Row) -> Thread:
        return Thread(
            thread_id=row["thread_id"],
            session_id=row["session_id"],
            title=row["title"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # ------------------------------------------------------------------
    # Session CRUD
    # ------------------------------------------------------------------
    def insert_session(self, session: Session) -> Session:
        self._conn.execute(
            "INSERT INTO sessions (session_id, novel_id, title, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                session.session_id,
                session.novel_id,
                session.title,
                session.created_at,
                session.updated_at,
            ),
        )
        self._conn.commit()
        return session

    def get_session(self, session_id: str) -> Session | None:
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        return self._row_to_session(row) if row else None

    def list_sessions(self) -> list[Session]:
        rows = self._conn.execute(
            "SELECT * FROM sessions ORDER BY created_at DESC"
        ).fetchall()
        return [self._row_to_session(r) for r in rows]

    def update_session(self, session: Session) -> Session:
        self._conn.execute(
            "UPDATE sessions SET novel_id=?, title=?, updated_at=? WHERE session_id=?",
            (session.novel_id, session.title, session.updated_at, session.session_id),
        )
        self._conn.commit()
        return session

    def delete_session(self, session_id: str) -> bool:
        # 先删线程记录，再删会话记录（同一事务）
        self._conn.execute("DELETE FROM threads WHERE session_id = ?", (session_id,))
        cur = self._conn.execute(
            "DELETE FROM sessions WHERE session_id = ?", (session_id,)
        )
        self._conn.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Thread CRUD
    # ------------------------------------------------------------------
    def insert_thread(self, thread: Thread) -> Thread:
        self._conn.execute(
            "INSERT INTO threads (thread_id, session_id, title, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                thread.thread_id,
                thread.session_id,
                thread.title,
                thread.created_at,
                thread.updated_at,
            ),
        )
        self._conn.commit()
        return thread

    def get_thread(self, thread_id: str) -> Thread | None:
        row = self._conn.execute(
            "SELECT * FROM threads WHERE thread_id = ?", (thread_id,)
        ).fetchone()
        return self._row_to_thread(row) if row else None

    def list_threads(self, session_id: str) -> list[Thread]:
        rows = self._conn.execute(
            "SELECT * FROM threads WHERE session_id = ? ORDER BY created_at ASC",
            (session_id,),
        ).fetchall()
        return [self._row_to_thread(r) for r in rows]

    def delete_thread(self, thread_id: str) -> bool:
        cur = self._conn.execute(
            "DELETE FROM threads WHERE thread_id = ?", (thread_id,)
        )
        self._conn.commit()
        return cur.rowcount > 0
