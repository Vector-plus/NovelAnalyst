"""SpaceStore —— 小说空间元数据的 SQLite 存储（标准库，无 ORM）。

元数据字段少、查询简单（按 id 精确查 / 全量列表），用 stdlib ``sqlite3`` 足够，
与项目极简风格一致（对比 memory 用 JSON、checkpointer 用 sqlite）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from deerflow_simple.spaces.models import NovelSpace

_SCHEMA = """
CREATE TABLE IF NOT EXISTS spaces (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    author TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class SpaceStore:
    """小说空间元数据的 SQLite 存取层。"""

    def __init__(self, db_path: str | Path):
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _row_to_space(row: sqlite3.Row) -> NovelSpace:
        return NovelSpace(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            author=row["author"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    def insert(self, space: NovelSpace) -> NovelSpace:
        self._conn.execute(
            "INSERT INTO spaces (id, name, description, author, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                space.id,
                space.name,
                space.description,
                space.author,
                space.created_at,
                space.updated_at,
            ),
        )
        self._conn.commit()
        return space

    def get(self, space_id: str) -> NovelSpace | None:
        row = self._conn.execute(
            "SELECT * FROM spaces WHERE id = ?", (space_id,)
        ).fetchone()
        return self._row_to_space(row) if row else None

    def list(self) -> list[NovelSpace]:
        rows = self._conn.execute(
            "SELECT * FROM spaces ORDER BY created_at DESC"
        ).fetchall()
        return [self._row_to_space(r) for r in rows]

    def update(self, space: NovelSpace) -> NovelSpace:
        self._conn.execute(
            "UPDATE spaces SET name=?, description=?, author=?, updated_at=? WHERE id=?",
            (space.name, space.description, space.author, space.updated_at, space.id),
        )
        self._conn.commit()
        return space

    def delete(self, space_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM spaces WHERE id = ?", (space_id,))
        self._conn.commit()
        return cur.rowcount > 0
