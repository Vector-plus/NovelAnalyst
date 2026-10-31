"""小说空间领域模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4


def now_iso() -> str:
    """当前 UTC 时间的 ISO 8601 字符串。"""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class NovelSpace:
    """小说空间元数据。

    ``id`` 即 novel_id（uuid4 hex），与小说空间根（space root）``workspace/{id}``
    一一对应（原文存 ``workspace/{id}/source/novel.txt``）。下游通过
    ``resolve_novel_path`` 映射 space root，通过 ``resolve_novel_index_path`` 映射
    索引树根（index root = ``workspace/{id}/novel``）。
    """

    name: str
    description: str = ""
    author: str = ""
    id: str = field(default_factory=lambda: uuid4().hex)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
