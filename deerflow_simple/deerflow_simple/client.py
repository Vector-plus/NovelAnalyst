"""SimpleClient —— 嵌入式客户端（最简入口）。

对应 DeerFlow 的 `client.py::DeerFlowClient`。不依赖 HTTP / FastAPI，用可配置的
checkpointer（memory / sqlite）做多轮记忆。

在「直接 `ainvoke`」之上，本客户端引入 DeerFlow 的 worker 协程管理机制：
内部维护一个常驻事件循环线程，所有 run 都通过 `RunManager` 准入并派发成
后台 `asyncio.Task`（对应 `start_run` + `run_agent`），从而支持：

- 后台非阻塞提交（`submit`）与等待（`wait`）
- 同线程串行 + reject / interrupt / rollback 多任务策略
- 取消（`cancel`）与状态查询（`status`）
"""

from __future__ import annotations

import asyncio
import queue
import threading
from typing import Iterator

from deerflow_simple.agent import build_agent
from deerflow_simple.checkpointer import acheckpointer_context
from deerflow_simple.config import SimpleConfig
from deerflow_simple.runs import RunManager, submit_run, wait_run
from deerflow_simple.sessions import new_id


# ---------------------------------------------------------------------------
# 进程内共享 event loop
#
# httpx / httpcore / anyio 的 HTTP 连接池会在「首次请求」时把底层 asyncio 对象
# 绑定到当时的 event loop，之后在其它 loop 上复用会抛
# ``... is bound to a different event loop``。因此不能让每个 SimpleClient 实例
# 各自 new_event_loop()，而应让进程内所有实例共享同一个常驻 loop。
# ---------------------------------------------------------------------------
_shared_loop: asyncio.AbstractEventLoop | None = None
_shared_loop_thread: threading.Thread | None = None
_shared_loop_lock = threading.Lock()


def _get_shared_loop() -> asyncio.AbstractEventLoop:
    """惰性创建并返回进程内共享的常驻 event loop（线程安全）。"""
    global _shared_loop, _shared_loop_thread
    with _shared_loop_lock:
        if _shared_loop is None:
            _shared_loop = asyncio.new_event_loop()
            _shared_loop_thread = threading.Thread(
                target=_shared_loop.run_forever,
                daemon=True,
                name="deerflow-simple-worker-loop",
            )
            _shared_loop_thread.start()
        return _shared_loop


class SimpleClient:
    """嵌入式 agent 客户端。

    用法::

        client = SimpleClient()
        print(client.chat("你好", thread_id="t1"))

        # worker 管理：后台提交 + 查询 + 取消
        run_id = client.submit("帮我写首诗", thread_id="t1")
        print(client.status(run_id))   # running
        client.cancel(run_id)
    """

    def __init__(self, config: SimpleConfig | None = None, extra_tools: list | None = None):
        self._config = config or SimpleConfig()

        # 共享常驻事件循环：所有后台 worker 协程、异步 checkpointer 的生命周期
        # 都跑在这个进程内共享的 loop 上（而非每实例新建，否则 httpx 连接池会
        # 因跨 loop 复用而报「bound to a different event loop」）。
        self._loop = _get_shared_loop()

        # 在共享 loop 上创建异步 checkpointer（sqlite 用 AsyncSqliteSaver，支持 astream）。
        # 持有 _cp_cm 引用保持连接常开，close() 时退出。
        self._cp_cm, self._checkpointer = self._sync(self._enter_checkpointer())
        self._graph = build_agent(self._config, checkpointer=self._checkpointer, extra_tools=extra_tools)
        self._run_manager = RunManager()

    def _sync(self, coro):
        """把协程调度到常驻 loop 并阻塞等待结果。"""
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    async def _enter_checkpointer(self):
        """在常驻 loop 上进入异步 checkpointer 上下文，返回 (cm, checkpointer)。"""
        cm = acheckpointer_context(self._config)
        checkpointer = await cm.__aenter__()
        return cm, checkpointer

    def close(self):
        """释放 checkpointer 连接（退出 checkpointer 上下文）。

        共享 event loop 线程为 daemon、随进程退出，这里**不**关闭 loop，只退出
        checkpointer 上下文、释放 sqlite 连接，使同一 db 文件可被新的 client
        实例重新打开。
        """
        self._sync(self._cp_cm.__aexit__(None, None, None))

    # ------------------------------------------------------------------
    # 同步便捷接口
    # ------------------------------------------------------------------
    def chat(
        self,
        message: str,
        thread_id: str = "default",
        novel_id: str | None = None,
        session_id: str | None = None,
    ) -> str:
        """同步对话，返回最终 AI 文本（提交 + 等待的便捷封装）。

        ``novel_id`` 绑定当前对话的小说空间，供解说工具通过代码注入（不交给 LLM）。
        ``session_id`` 会话 id；None 时自动生成，用于 LangSmith 会话归组。
        """
        return self._sync(
            self.chat_async(message, thread_id, novel_id=novel_id, session_id=session_id)
        )

    def stream(
        self,
        message: str,
        thread_id: str = "default",
        novel_id: str | None = None,
        session_id: str | None = None,
    ) -> Iterator[dict]:
        """流式对话（结构化事件流，yield 事件 dict）。

        底层走 worker + ``on_event`` 回调，用队列把异步事件流桥接成同步生成器。

        事件协议见 ``stream.py``：``message``（模型文本 delta）/ ``reasoning``
        （推理内容 delta）/ ``tool_call``（工具调用）/ ``tool_result``（工具返回）/
        ``done``（终态），每个事件带 ``source`` 字段区分 lead / narration。

        ``novel_id`` 绑定当前对话的小说空间，供解说工具通过代码注入（不交给 LLM）。
        ``session_id`` 会话 id；None 时自动生成。
        """
        if session_id is None:
            session_id = new_id()
        out_queue: queue.Queue = queue.Queue()

        def on_event(event: dict) -> None:
            out_queue.put(event)

        def _produce() -> None:
            try:
                run_id = self._sync(
                    submit_run(
                        self._run_manager,
                        self._graph,
                        message,
                        thread_id,
                        recursion_limit=self._config.recursion_limit,
                        novel_id=novel_id,
                        session_id=session_id,
                        on_event=on_event,
                        max_tool_calls=self._config.agent_max_tool_calls,
                        token_budget=self._config.agent_token_budget,
                    )
                )
                self._sync(wait_run(self._run_manager, run_id))
            except Exception:
                # 出错也保证生成器能正常结束，不悬挂
                pass
            finally:
                out_queue.put(None)  # 结束标记

        threading.Thread(target=_produce, daemon=True).start()

        while True:
            event = out_queue.get()
            if event is None:
                break
            yield event

    def stream_text(
        self,
        message: str,
        thread_id: str = "default",
        novel_id: str | None = None,
        session_id: str | None = None,
    ) -> Iterator[str]:
        """流式对话（仅模型文本，向后兼容便捷方法）。

        内部复用 ``stream``，只 yield ``message`` 事件的文本 delta。
        """
        for event in self.stream(
            message, thread_id=thread_id, novel_id=novel_id, session_id=session_id
        ):
            if event.get("type") == "message":
                yield event.get("content", "")

    # ------------------------------------------------------------------
    # worker 管理接口（同步）
    # ------------------------------------------------------------------
    def submit(
        self,
        message: str,
        thread_id: str = "default",
        multitask_strategy: str = "reject",
        novel_id: str | None = None,
        session_id: str | None = None,
    ) -> str:
        """后台提交一个 run，立即返回 run_id（非阻塞）。

        ``multitask_strategy`` 决定同线程已有活跃 run 时的行为：
        reject（抛 :class:`ConflictError`）/ interrupt / rollback。

        ``novel_id`` 绑定当前对话的小说空间，供解说工具通过代码注入（不交给 LLM）。
        ``session_id`` 会话 id；None 时自动生成。
        """
        return self._sync(
            self.submit_async(
                message,
                thread_id,
                multitask_strategy=multitask_strategy,
                novel_id=novel_id,
                session_id=session_id,
            )
        )

    def wait(self, run_id: str, timeout: float | None = None) -> str:
        """阻塞等待一个 run 完成，返回最终 AI 文本。"""
        return self._sync(self.wait_async(run_id, timeout=timeout))

    def cancel(self, run_id: str) -> bool:
        """取消一个活跃 run。"""
        return self._run_manager.cancel(run_id)

    def status(self, run_id: str) -> str | None:
        """查询 run 当前状态（pending/running/success/error/interrupted）。"""
        record = self._run_manager.get(run_id)
        return record.status.value if record is not None else None

    # ------------------------------------------------------------------
    # worker 管理接口（异步，供已有事件循环内调用）
    # ------------------------------------------------------------------
    async def chat_async(
        self,
        message: str,
        thread_id: str = "default",
        novel_id: str | None = None,
        session_id: str | None = None,
    ) -> str:
        run_id = await self.submit_async(
            message, thread_id, novel_id=novel_id, session_id=session_id
        )
        return await self.wait_async(run_id)

    async def submit_async(
        self,
        message: str,
        thread_id: str = "default",
        multitask_strategy: str = "reject",
        novel_id: str | None = None,
        session_id: str | None = None,
    ) -> str:
        if session_id is None:
            session_id = new_id()
        return await submit_run(
            self._run_manager,
            self._graph,
            message,
            thread_id,
            multitask_strategy=multitask_strategy,
            recursion_limit=self._config.recursion_limit,
            novel_id=novel_id,
            session_id=session_id,
            max_tool_calls=self._config.agent_max_tool_calls,
            token_budget=self._config.agent_token_budget,
        )

    async def wait_async(self, run_id: str, timeout: float | None = None) -> str:
        return await wait_run(self._run_manager, run_id, timeout=timeout)