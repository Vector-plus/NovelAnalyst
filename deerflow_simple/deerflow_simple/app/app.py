"""FastAPI 应用工厂 —— 为 worker 协程管理机制暴露 HTTP API。

对应 DeerFlow 的 `app/gateway/app.py::create_app` 的 run 部分。

精简为一个最小可用的 API 网关：构建一次共享的 agent graph + RunManager，
挂到 ``app.state`` 上，多个请求复用同一套协程管理基础设施。

会话持久化（本期新增）：用 lifespan 管理异步 checkpointer（AsyncSqliteSaver /
InMemorySaver），并在其上构建带 checkpointer 的 lead_agent graph，使同一
``thread_id`` 的多轮对话在进程重启后仍可恢复（checkpoint key = thread_id）。
同时挂载 sessions 模块（会话/线程元数据），提供 session_id/thread_id 的
业务归组与 LangSmith 追踪注入。

启动方式::

    uvicorn deerflow_simple.app.app:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from deerflow_simple.agent import build_agent
from deerflow_simple.checkpointer import acheckpointer_context
from deerflow_simple.config import SimpleConfig
from deerflow_simple.runs import RunManager

def create_app(config: SimpleConfig | None = None) -> FastAPI:
    """创建并配置 FastAPI 应用。"""
    config = config or SimpleConfig()

    # 挂载 generate_narration 工具（小说解说词工作流入口）。
    # 与 examples/11_narration_client.py 一致：lead_agent 通过该工具触发解说，
    # novel_id 由代码从 graph state 经 InjectedState 注入，不交给 LLM 决策。
    # skills_dir=None 时，NarrationAgent 内部 fallback 到默认 examples/skills。
    from deerflow_simple.narration import build_generate_narration_tool

    narration_tool = build_generate_narration_tool(config)

    # RunManager 全局共享，所有 run 在其上准入、串行、取消。
    run_manager = RunManager()

    # 小说空间：元数据存储 + 管理器（纯后端，无 LLM）
    from deerflow_simple.spaces import SpaceManager, SpaceStore

    space_store = SpaceStore(config.spaces_db)
    space_manager = SpaceManager(config, space_store)

    # 会话：元数据存储（sessions/threads 表）。SessionManager 需在 lifespan 里
    # 拿到 checkpointer 后才能构建（级联删除 checkpoint 需要 checkpointer 引用）。
    from deerflow_simple.sessions import SessionManager, SessionStore

    session_store = SessionStore(config.sessions_db)

    # 长任务运行时（索引生成等）：通用「任务 + SSE 进度 + 暂停/恢复」基础设施。
    # index graph 由 tasks 模块的 TaskManager 驱动执行，task_id 维度（非对话 thread_id）。
    from deerflow_simple.index_builder import build_index_graph
    from deerflow_simple.tasks import TaskManager, TaskStore

    index_graph = build_index_graph(config)
    task_store = TaskStore(config.tasks_db)
    task_manager = TaskManager(config, task_store, index_graph)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 进入异步 checkpointer 上下文（memory 直接返回 InMemorySaver；
        # sqlite 返回 AsyncSqliteSaver），保持连接常开直到应用关闭。
        cp_cm = acheckpointer_context(config)
        checkpointer = await cp_cm.__aenter__()

        # 在带 checkpointer 的情况下重新编译 graph（持久化对话状态）。
        graph = build_agent(
            config, checkpointer=checkpointer, extra_tools=[narration_tool]
        )

        app.state.checkpointer = checkpointer
        app.state._cp_cm = cp_cm
        app.state.graph = graph
        app.state.session_manager = SessionManager(session_store, checkpointer)
        try:
            yield
        finally:
            await cp_cm.__aexit__(None, None, None)

    app = FastAPI(
        title="DeerFlow Simple API",
        description=(
            "从 DeerFlow 提炼的最小 agent HTTP API，"
            "基于 RunManager 准入 + 后台 run_agent 协程消费。"
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    app.state.run_manager = run_manager
    app.state.config = config
    app.state.space_store = space_store
    app.state.space_manager = space_manager
    app.state.session_store = session_store
    app.state.task_store = task_store
    app.state.task_manager = task_manager

    from deerflow_simple.app.routers import runs
    from deerflow_simple.sessions.router import router as sessions_router
    from deerflow_simple.spaces.router import router as spaces_router

    app.include_router(runs.router)
    app.include_router(sessions_router)
    app.include_router(spaces_router)

    from deerflow_simple.app.routers import tasks

    app.include_router(tasks.router)

    @app.get("/health")
    async def health() -> dict:
        """健康检查。"""
        return {"status": "ok"}

    return app


app = create_app()
