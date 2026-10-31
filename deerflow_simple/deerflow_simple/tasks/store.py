"""TaskStore —— 长任务记录的 SQLite 持久化（标准库，无 ORM）。

任务记录字段少、查询简单（按 task_id 精确查 / 按 novel_id 过滤 / 全量列表），
用 stdlib ``sqlite3`` 足够，与 SpaceStore 的极简风格一致。

只持久化「生命周期」字段（task_id / novel_id / kind / status / phase / error /
时间戳）；运行时字段（协程、事件队列、取消信号）不落盘——它们随进程生命周期，
重启后任务记录仍在（可 list/get），但需通过 checkpoint 恢复继续执行。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from deerflow_simple.tasks.schemas import TaskRecord, TaskStatus

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    novel_id TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'index_build',
    status TEXT NOT NULL,
    phase TEXT NOT NULL DEFAULT '',
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class TaskStore:
    """长任务记录的 SQLite 存取层。"""

    def __init__(self, db_path: str | Path):
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> TaskRecord:
        return TaskRecord(
            task_id=row["task_id"],
            novel_id=row["novel_id"],
            kind=row["kind"],
            status=TaskStatus(row["status"]),
            phase=row["phase"],
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    def insert(self, record: TaskRecord) -> TaskRecord:
        self._conn.execute(
            "INSERT INTO tasks (task_id, novel_id, kind, status, phase, error, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.task_id,
                record.novel_id,
                record.kind,
                record.status.value,
                record.phase,
                record.error,
                record.created_at,
                record.updated_at,
            ),
        )
        self._conn.commit()
        return record

    def get(self, task_id: str) -> TaskRecord | None:
        row = self._conn.execute(
            "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        return self._row_to_record(row) if row else None

    def list(self, novel_id: str | None = None) -> list[TaskRecord]:
        if novel_id:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE novel_id = ? ORDER BY created_at DESC",
                (novel_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC"
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def update(self, record: TaskRecord) -> TaskRecord:
        self._conn.execute(
            "UPDATE tasks SET status=?, phase=?, error=?, updated_at=? WHERE task_id=?",
            (
                record.status.value,
                record.phase,
                record.error,
                record.updated_at,
                record.task_id,
            ),
        )
        self._conn.commit()
        return record

    def delete(self, task_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
        self._conn.commit()
        return cur.rowcount > 0
