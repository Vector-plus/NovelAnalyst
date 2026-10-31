"""TaskManager —— 长任务生命周期管理（start / resume / cancel / 查询）。

与 ``runs.RunManager`` 分离的原因：RunManager 管「对话 run」（thread_id 维度、秒级、
内存态），长任务是「task_id 维度、小时~天级、sqlite 持久化」。二者生命周期完全不同，
强行合并会让职责爆炸。

职责边界：
- 持久化任务记录（``TaskStore``，决策 A2：重启后 list 仍可见）。
- 维护运行时记录（协程 / 事件队列 / 取消信号），这些不落盘。
- 启动后台协程（``runtime.run_task``）驱动 graph 执行。
- resume 时用 ``graph.update_state`` 注入人工决策，再从 checkpoint 继续。

一期边界（决策 C1）：只支持 Human-in-Loop interrupt（``review_plan`` 等人工），
不做「运行中强制暂停」。checkpointer 默认 InMemorySaver（支持 interrupt + 进程内
resume），跨进程重启恢复留待二期。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from deerflow_simple.tasks.runtime import run_task
from deerflow_simple.tasks.schemas import TaskRecord, TaskStatus
from deerflow_simple.tasks.store import TaskStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskManager:
    """长任务管理器。"""

    def __init__(self, config: Any, store: TaskStore, graph: Any):
        self._config = config
        self._store = store
        self._graph = graph
        # 运行时记录（含协程 / 事件队列 / 取消信号），不持久化。
        self._records: dict[str, TaskRecord] = {}
        # 进程重启后对账：把遗留的非终态任务统一标记为 cancelled（见方法注释）。
        self._reconcile_stale_tasks()

    def _reconcile_stale_tasks(self) -> None:
        """进程重启后，把遗留的非终态任务统一标记为 cancelled。

        一期 checkpointer 用 InMemorySaver，graph 的执行状态（checkpoint）随进程
        一起丢失；sqlite 里残留的 pending/running/paused 任务已无法继续（paused 的
        interrupt 恢复点也在内存里，一并丢失）。若不处理，用户查询会看到「running」，
        但任务其实已经死了，造成僵尸状态。故重启时统一落为 cancelled。

        这是决策 A2（task 记录持久化）与「checkpointer 一期用 InMemorySaver」两层
        能力不同步的必然结果：记录在、执行态不在。二期切 AsyncSqliteSaver 后，
        本方法应改为只对 running/pending 对账，paused 可跨重启保留。
        """
        for record in self._store.list():
            if record.status in (
                TaskStatus.pending,
                TaskStatus.running,
                TaskStatus.paused,
            ):
                record.status = TaskStatus.cancelled
                record.updated_at = _now_iso()
                self._store.update(record)

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------
    def _config_for(self, task_id: str) -> dict[str, Any]:
        return {
            "configurable": {"thread_id": task_id},
            "recursion_limit": self._config.recursion_limit,
        }

    def _runtime_record(self, task_id: str) -> TaskRecord:
        """取运行时记录；内存没有（如重启后）则从 store 兜底加载。"""
        record = self._records.get(task_id)
        if record is not None:
            return record
        stored = self._store.get(task_id)
        if stored is None:
            raise KeyError(f"未知任务: {task_id}")
        stored.event_queue = asyncio.Queue()
        self._records[task_id] = stored
        return stored

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def get(self, task_id: str) -> TaskRecord | None:
        record = self._records.get(task_id)
        if record is not None:
            return record
        return self._store.get(task_id)

    def list(self, novel_id: str | None = None) -> list[TaskRecord]:
        return self._store.list(novel_id)

    def get_event_queue(self, task_id: str) -> asyncio.Queue | None:
        record = self._records.get(task_id)
        return record.event_queue if record is not None else None

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    async def start(
        self,
        novel_id: str,
        input_payload: dict[str, Any],
        kind: str = "index_build",
    ) -> str:
        """创建任务并启动后台协程，返回 task_id（非阻塞）。

        ``input_payload`` 是 graph 的初始输入（含 novel_id / task_id / build_mode 等），
        由调用方（index_builder 入口 / HTTP 路由）构造，manager 不关心 graph 内部结构。
        """
        task_id = uuid4().hex
        now = _now_iso()
        record = TaskRecord(
            task_id=task_id,
            novel_id=novel_id,
            kind=kind,
            created_at=now,
            updated_at=now,
        )
        record.event_queue = asyncio.Queue()
        self._store.insert(record)
        self._records[task_id] = record

        worker = run_task(
            record,
            graph=self._graph,
            input_payload=input_payload,
            config=self._config_for(task_id),
            manager=self,
        )
        record.task = asyncio.create_task(worker, name=f"deerflow-task-{task_id}")
        return task_id

    async def resume(self, task_id: str, decision: dict[str, Any] | None = None) -> None:
        """恢复一个 paused 任务。

        - ``decision`` 非空：Human-in-Loop 决策（形如 ``{"decision": "approve"}`` /
          ``{"decision": "reject"}``），先 ``graph.update_state`` 注入
          ``pending_human_decision``，再从 checkpoint 继续。
        - ``decision`` 为空：崩溃/暂停后的续跑（一期主要为前者）。

        Raises:
            RuntimeError: 任务不在 paused 态（cancelled/failed/done 不可恢复）。
            ValueError: decision 格式非法（缺少 decision 键或取值不在 approve/reject）。
        """
        record = self._runtime_record(task_id)
        if record.status != TaskStatus.paused:
            raise RuntimeError(
                f"任务 {task_id} 不是 paused 状态（当前: {record.status.value}），"
                "cancelled/failed/done 任务无法恢复，请重新创建任务"
            )

        # 重置取消信号：若该任务此前被 cancel 过，abort_event 已置位；不 clear 的话，
        # resume 后的 run_task 一进来就会检测到 abort 并立即再次 cancelled。
        record.abort_event.clear()

        config = self._config_for(task_id)
        if decision is not None:
            action = decision.get("decision")
            if action not in ("approve", "reject"):
                raise ValueError(
                    f"无效的人工决策 {decision!r}：decision.decision 应为 'approve' 或 'reject'"
                )
            self._graph.update_state(config, {"pending_human_decision": decision})

        worker = run_task(
            record,
            graph=self._graph,
            input_payload=None,  # 从 checkpoint 继续
            config=config,
            manager=self,
        )
        record.task = asyncio.create_task(worker, name=f"deerflow-task-{task_id}")

    async def cancel(self, task_id: str) -> bool:
        """取消一个活跃任务（置位 abort_event 并 cancel 后台协程）。"""
        record = self._records.get(task_id)
        if record is None or record.status not in (TaskStatus.pending, TaskStatus.running, TaskStatus.paused):
            return False
        record.abort_event.set()
        if record.task is not None and not record.task.done():
            record.task.cancel()
        await self.set_status(task_id, TaskStatus.cancelled)
        return True

    # ------------------------------------------------------------------
    # 状态更新（供 runtime 回调）
    # ------------------------------------------------------------------
    async def set_status(self, task_id: str, status: TaskStatus, error: str | None = None) -> None:
        record = self._runtime_record(task_id)
        record.status = status
        if error is not None:
            record.error = error
        record.updated_at = _now_iso()
        self._store.update(record)

    async def set_phase(self, task_id: str, phase: str) -> None:
        record = self._runtime_record(task_id)
        record.phase = phase
        record.updated_at = _now_iso()
        self._store.update(record)

    async def emit(self, task_id: str, event: dict[str, Any]) -> None:
        """把事件放入任务的事件队列（SSE 端点从队列消费）。"""
        record = self._records.get(task_id)
        if record is not None and record.event_queue is not None:
            record.event_queue.put_nowait(event)
