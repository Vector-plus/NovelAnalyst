"""RunManager —— 内存 run 注册表 + 同线程串行 + 启动屏障。

对应 DeerFlow 的 `runtime/runs/manager.py::RunManager`。

去掉 store 持久化、lease 租约、幂等键等跨进程能力，只保留单进程协程管理核心：

- `create_or_reject`：原子准入，支持 reject / interrupt / rollback 三种策略
- `try_start`：pending → running 启动屏障（可被取消）
- `wait_for_prior_finalizing`：同线程串行排队
- `cancel`：`abort_event.set()` + `task.cancel()` 双重取消

所有变更由一把 `asyncio.Lock` 保护，保证同线程并发提交时状态一致。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from deerflow_simple.runs.schemas import RunRecord, RunStartOutcome, RunStatus

_SUPPORTED_STRATEGIES = ("reject", "interrupt", "rollback")


class ConflictError(Exception):
    """线程已有活跃 run（reject 策略下抛出）。"""


class UnsupportedStrategyError(Exception):
    """传入了未实现的多任务策略。"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunManager:
    """内存 run 注册表。"""

    def __init__(self) -> None:
        self._runs: dict[str, RunRecord] = {}
        # 二级索引：thread_id -> 有序 run_id 集合（dict 充当有序 set），
        # 与 ``_runs`` 在同一把锁下同步增删，避免按线程查询全表扫描。
        self._runs_by_thread: dict[str, dict[str, None]] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # 索引维护（调用方必须持有 self._lock）
    # ------------------------------------------------------------------
    def _index_run_locked(self, record: RunRecord) -> None:
        self._runs_by_thread.setdefault(record.thread_id, {})[record.run_id] = None

    def _unindex_run_locked(self, run_id: str, thread_id: str) -> None:
        bucket = self._runs_by_thread.get(thread_id)
        if bucket is not None:
            bucket.pop(run_id, None)
            if not bucket:
                self._runs_by_thread.pop(thread_id, None)

    def _thread_records_locked(self, thread_id: str) -> list[RunRecord]:
        """返回某线程所有在内存中的 run 记录（按插入顺序）。"""
        run_ids = self._runs_by_thread.get(thread_id)
        if not run_ids:
            return []
        return [record for run_id in run_ids if (record := self._runs.get(run_id)) is not None]

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def get(self, run_id: str) -> RunRecord | None:
        return self._runs.get(run_id)

    def list_by_thread(self, thread_id: str) -> list[RunRecord]:
        return self._thread_records_locked(thread_id)

    # ------------------------------------------------------------------
    # 准入
    # ------------------------------------------------------------------
    async def create_or_reject(
        self,
        thread_id: str,
        *,
        multitask_strategy: str = "reject",
    ) -> RunRecord:
        """原子地为一个线程准入一个新 run。

        - ``reject``：线程已有 pending/running/finalizing 的 run 时抛
          :class:`ConflictError`（对应 DeerFlow 的 409）。
        - ``interrupt`` / ``rollback``：先取消现有活跃 run 再创建新 run。
          简化版二者等价（都通过 abort_event + task.cancel 终止旧 run）。
        """
        if multitask_strategy not in _SUPPORTED_STRATEGIES:
            raise UnsupportedStrategyError(
                f"Multitask strategy '{multitask_strategy}' is not supported. "
                f"Supported: {', '.join(_SUPPORTED_STRATEGIES)}"
            )

        run_id = str(uuid4())
        now = _now_iso()
        record = RunRecord(
            run_id=run_id,
            thread_id=thread_id,
            status=RunStatus.pending,
            multitask_strategy=multitask_strategy,
            created_at=now,
            updated_at=now,
        )

        async with self._lock:
            inflight = [
                r
                for r in self._thread_records_locked(thread_id)
                if r.status in (RunStatus.pending, RunStatus.running) or r.finalizing
            ]

            if multitask_strategy == "reject" and inflight:
                raise ConflictError(f"Thread {thread_id} already has an active run")

            if multitask_strategy in ("interrupt", "rollback") and inflight:
                for r in inflight:
                    if r.finalizing:
                        continue
                    r.abort_action = multitask_strategy
                    r.abort_event.set()
                    if r.task is not None and not r.task.done():
                        r.task.cancel()
                    r.status = RunStatus.interrupted
                    r.updated_at = now

            # 本地检查通过后再注册，保证 register 与本地 reject 判断同锁原子。
            self._runs[run_id] = record
            self._index_run_locked(record)

        return record

    # ------------------------------------------------------------------
    # 启动屏障
    # ------------------------------------------------------------------
    async def try_start(self, run_id: str) -> RunStartOutcome:
        """把一个未取消的 pending run 置为 running。

        若 run 已被取消（abort_event 置位）或已不在 pending 态，返回
        ``cancelled``，worker 据此跳过 agent 构建与执行。
        """
        record = self._runs.get(run_id)
        if record is None:
            raise RuntimeError(f"Cannot start unknown run {run_id}")

        async with record.start_lock:
            if record.abort_event.is_set() or record.status != RunStatus.pending:
                return RunStartOutcome.cancelled
            record.status = RunStatus.running
            record.updated_at = _now_iso()
            return RunStartOutcome.started

    async def wait_for_prior_finalizing(
        self,
        thread_id: str,
        run_id: str,
        *,
        poll_interval: float = 0.01,
        abort_event: asyncio.Event | None = None,
    ) -> None:
        """等待同线程更早的、正在收尾的 run 完成清理。

        这是同线程任务串行化的关键屏障：一个 run 只有等排在自己前面的
        finalizing run 全部收尾后才会继续（对应 DeerFlow 的同名方法）。
        """
        while True:
            async with self._lock:
                found_current = False
                prior_finalizing = False
                for record in self._thread_records_locked(thread_id):
                    if record.run_id == run_id:
                        found_current = True
                        break
                    if record.finalizing:
                        prior_finalizing = True

                if not found_current or not prior_finalizing:
                    return

            if abort_event is None:
                await asyncio.sleep(poll_interval)
                continue
            try:
                await asyncio.wait_for(abort_event.wait(), timeout=poll_interval)
            except TimeoutError:
                continue
            return

    # ------------------------------------------------------------------
    # 状态更新
    # ------------------------------------------------------------------
    async def set_status(
        self,
        run_id: str,
        status: RunStatus,
        *,
        error: str | None = None,
        result: str | None = None,
    ) -> None:
        record = self._runs.get(run_id)
        if record is None:
            return
        record.status = status
        if error is not None:
            record.error = error
        if result is not None:
            record.result = result
        record.updated_at = _now_iso()

    async def set_finalizing(self, run_id: str, value: bool) -> None:
        record = self._runs.get(run_id)
        if record is not None:
            record.finalizing = value

    # ------------------------------------------------------------------
    # 取消
    # ------------------------------------------------------------------
    def cancel(self, run_id: str) -> bool:
        """取消一个活跃 run（置位 abort_event 并 cancel 后台 task）。

        同步方法：`Event.set()` 与 `Task.cancel()` 都是非阻塞的，可跨线程调用。
        返回是否真正对一个活跃 run 生效。

        注意这里**立即把状态落为 interrupted**：Python asyncio 对尚未被调度
        运行的 task 调用 ``cancel()`` 会直接跳过协程体（不执行 try/except/finally），
        所以不能依赖 worker 收尾来设置状态。
        """
        record = self._runs.get(run_id)
        if record is None or record.status not in (RunStatus.pending, RunStatus.running):
            return False
        record.abort_event.set()
        record.status = RunStatus.interrupted
        record.updated_at = _now_iso()
        if record.task is not None and not record.task.done():
            record.task.cancel()
        return True
