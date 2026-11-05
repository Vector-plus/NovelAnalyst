"""会话（Session）与线程（Thread）领域模型。

会话是业务层的对话容器（1 个 session 包含 1..N 个 thread），
thread 才是 LangGraph checkpointer 的执行 key（决定多轮历史累积/恢复）。

``session_id`` 与 ``thread_id`` 都用 LangSmith 提供的 UUIDv7 生成：
时间有序、可索引，便于 LangSmith 侧按时间排序与高效过滤。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from langsmith import uuid7


def new_id() -> str:
    """生成时间有序的 UUIDv7 字符串（LangSmith 提供）。"""
    return str(uuid7())


def now_iso() -> str:
    """当前 UTC 时间的 ISO 8601 字符串。"""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Session:
    """业务会话容器（绑定一本小说，其下可开多个 thread）。"""

    session_id: str = field(default_factory=new_id)
    novel_id: str | None = None
    title: str = ""
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)


@dataclass
class Thread:
    """会话下的一条独立对话时间线（即 LangGraph checkpoint 的 key）。"""

    thread_id: str = field(default_factory=new_id)
    session_id: str = ""
    title: str = ""
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
