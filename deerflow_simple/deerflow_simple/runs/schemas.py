"""run 生命周期相关的枚举与数据结构。

对应 DeerFlow 的 `runtime/runs/schemas.py::RunStatus` + `manager.py::RunRecord`。

精简掉 store 持久化、lease 租约、token 统计、幂等键等企业级字段，只保留
worker 协程管理所需的最小集合：

- `run_id` / `thread_id`：run 与线程标识
- `status`：pending → running → 终态（success / error / interrupted）
- `task`：后台 worker 协程（`asyncio.Task`）
- `abort_event`：取消信号（worker 在 chunk 边界检查它）
- `start_lock`：pending → running 启动屏障锁
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum


class RunStatus(StrEnum):
    """单个 run 的生命周期状态。"""

    pending = "pending"
    running = "running"
    success = "success"
    error = "error"
    interrupted = "interrupted"


class RunStartOutcome(StrEnum):
    """pending → running 启动屏障的结果。"""

    started = "started"
    cancelled = "cancelled"


@dataclass
class RunRecord:
    """一次 run 的可变内存记录。

    一个 run 对应一次「用户消息 → agent 后台消费」的完整过程。字段分三类：

    - 标识/策略：`run_id`、`thread_id`、`multitask_strategy`
    - 生命周期：`status`、`finalizing`、`error`、`result`
    - 协程控制：`task`、`abort_event`、`start_lock`、`abort_action`
    """

    run_id: str
    thread_id: str
    status: RunStatus = RunStatus.pending
    # 同线程已有活跃 run 时的处理策略：reject / interrupt / rollback
    multitask_strategy: str = "reject"
    # 后台 worker 协程，由 submit_run 挂载（repr 里不展开，避免打印 task 堆栈）
    task: asyncio.Task | None = field(default=None, repr=False)
    # 启动屏障锁：同一 run 若被多个 worker 路径接管，串行化其启动
    start_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    # 取消信号：置位后 worker 在下一个 chunk 边界停止
    abort_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    # 取消动作：interrupt（仅标记中断）/ rollback（回滚，简化版二者等价）
    abort_action: str = "interrupt"
    error: str | None = None
    # 最终 AI 文本（success 时有效）
    result: str | None = None
    # 是否正在收尾；同线程后续 run 需等它置回 False 才能启动
    finalizing: bool = False
    created_at: str = ""
    updated_at: str = ""
