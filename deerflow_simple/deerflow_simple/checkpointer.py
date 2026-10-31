"""checkpointer 工厂 —— 对话状态持久化。

简化自 DeerFlow 的 ``runtime/checkpointer/provider.py``（同步）与
``runtime/checkpointer/async_provider.py``（异步），保留 memory / sqlite 两种后端，
按 deerflow-simple 的裁剪原则移除 postgres、delta-history 缓存、单例与跨进程锁等企业级能力。

- ``memory``：进程内 InMemorySaver（默认，重启即丢）。
- ``sqlite``：本地文件持久化（需额外安装 ``langgraph-checkpoint-sqlite``；
  异步后端还需 ``aiosqlite``）。

同步工厂 ``checkpointer_context`` 产出 ``SqliteSaver``，用于 ``graph.invoke``；
异步工厂 ``acheckpointer_context`` 产出 ``AsyncSqliteSaver``，用于 ``graph.astream``
（``SimpleClient`` 走 ``astream`` 异步消费，故使用后者）。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Checkpointer

from deerflow_simple.config import SimpleConfig

logger = logging.getLogger(__name__)

_SQLITE_INSTALL = (
    "使用 SQLite checkpointer 需要 langgraph-checkpoint-sqlite（异步后端还需 aiosqlite），"
    "请先安装：uv sync --extra sqlite"
)


def _resolve_sqlite_conn_str(raw: str) -> str:
    """返回可直接用于 ``SqliteSaver.from_conn_string`` 的连接串。

    简化自 DeerFlow 的 ``runtime/store/_sqlite_utils.py``：
    - ``:memory:`` 原样返回；
    - 普通路径解析为绝对路径；
    - SQLite ``file:`` URI 拒绝（LangGraph 的 from_conn_string 不启用 uri=True）。
    """
    if raw.startswith("file:"):
        raise ValueError(
            f"SQLite URI 连接串不受支持：{raw!r}。请改用文件路径或 ':memory:'。"
        )
    if raw == ":memory:":
        return raw
    return str(Path(raw).expanduser().resolve())


@contextmanager
def checkpointer_context(config: SimpleConfig) -> Iterator[Checkpointer]:
    """创建并管理一个 checkpointer 的生命周期。

    与 DeerFlow 的 ``checkpointer_context`` 对齐，但只保留 memory / sqlite：

    - memory：直接 yield 一个 ``InMemorySaver``。
    - sqlite：进入 ``SqliteSaver.from_conn_string`` 上下文、执行 ``setup()`` 后 yield。

    调用方若需常驻 checkpointer（如 :class:`SimpleClient` 的多轮对话），
    用 ``cm = checkpointer_context(config); cp = cm.__enter__()`` 并持有 ``cm``
    引用以保持连接常开；一次性使用则直接 ``with checkpointer_context(config) as cp:``。
    """
    if config.checkpointer_type == "memory":
        logger.info("Checkpointer: 使用 InMemorySaver（进程内，不持久化）")
        yield InMemorySaver()
        return

    if config.checkpointer_type == "sqlite":
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver
        except ImportError as exc:
            raise ImportError(_SQLITE_INSTALL) from exc

        conn_str = _resolve_sqlite_conn_str(config.checkpointer_conn_str)
        if conn_str != ":memory:":
            Path(conn_str).parent.mkdir(parents=True, exist_ok=True)
        with SqliteSaver.from_conn_string(conn_str) as saver:
            saver.setup()
            logger.info("Checkpointer: 使用 SqliteSaver（%s）", conn_str)
            yield saver
        return

    raise ValueError(f"未知的 checkpointer 类型：{config.checkpointer_type!r}")


@asynccontextmanager
async def acheckpointer_context(config: SimpleConfig) -> AsyncIterator[Checkpointer]:
    """异步 checkpointer 工厂（用于 ``graph.astream``）。

    与 DeerFlow 的 ``async_provider._async_checkpointer`` 对齐：
    - memory：``InMemorySaver``（同时支持 sync/async 接口）。
    - sqlite：``AsyncSqliteSaver``（其 ``from_conn_string`` 为异步上下文管理器），
      进入后执行 ``await saver.setup()``。

    ``SimpleClient`` 通过 ``graph.astream`` 异步消费，必须使用本工厂；
    ``checkpointer_context`` 产出的是同步 ``SqliteSaver``，仅适用于 ``graph.invoke``。
    """
    if config.checkpointer_type == "memory":
        logger.info("Checkpointer: 使用 InMemorySaver（进程内，不持久化）")
        yield InMemorySaver()
        return

    if config.checkpointer_type == "sqlite":
        try:
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        except ImportError as exc:
            raise ImportError(_SQLITE_INSTALL) from exc

        conn_str = _resolve_sqlite_conn_str(config.checkpointer_conn_str)
        if conn_str != ":memory:":
            Path(conn_str).parent.mkdir(parents=True, exist_ok=True)
        async with AsyncSqliteSaver.from_conn_string(conn_str) as saver:
            await saver.setup()
            logger.info("Checkpointer: 使用 AsyncSqliteSaver（%s）", conn_str)
            yield saver
        return

    raise ValueError(f"未知的 checkpointer 类型：{config.checkpointer_type!r}")
