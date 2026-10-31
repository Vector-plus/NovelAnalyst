"""长任务生命周期相关的枚举与数据结构。

对应设计文档《03-核心图设计_索引生成.md》§4 的 task 生命周期，但与对话 run
（``runs`` 模块）分离：对话 run 是「一条消息 → 一次 agent 消费」，秒~分钟级；
长任务（索引生成）是「一个 task_id → 跨多次对话/跨进程重启」，小时~天级。

关键差异：
- 维度：``task_id``（任务）而非 ``thread_id``（对话）。
- 状态机：多了 ``paused``（等待人工决策，对应 LangGraph interrupt）。
- 持久化：task 记录落 sqlite（``TaskStore``），重启后仍可 list/get。

运行时字段（``task`` / ``event_queue`` / ``abort_event``）不持久化。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class TaskStatus(StrEnum):
    """单个长任务的生命周期状态。"""

    pending = "pending"      # 已创建，尚未开始执行
    running = "running"      # 正在执行
    paused = "paused"        # 等待人工决策（Human-in-Loop interrupt）
    done = "done"            # 正常完成
    failed = "failed"        # 执行失败
    cancelled = "cancelled"  # 已取消


@dataclass
class TaskRecord:
    """一次长任务的可变记录。

    字段分三类：
    - 标识/绑定：``task_id``、``novel_id``、``kind``
    - 生命周期（持久化）：``status``、``phase``、``error``、时间戳
    - 协程控制（不持久化）：``task``、``event_queue``、``abort_event``

    ``phase`` 记录当前 Graph 所处阶段（skeleton/prescan/review_plan/...），
    随 Graph 的 updates 事件推进，供前端展示「宏观进度」。
    """

    task_id: str
    novel_id: str
    kind: str = "index_build"          # 任务类型（index_build / narration / ...）
    status: TaskStatus = TaskStatus.pending
    phase: str = ""                    # 当前 Graph 阶段（节点名）
    error: str | None = None
    # 后台 worker 协程（不持久化）
    task: asyncio.Task | None = field(default=None, repr=False)
    # SSE 事件队列（不持久化）：后台协程把事件放入，SSE 端点从队列消费
    event_queue: asyncio.Queue | None = field(default=None, repr=False)
    # 取消信号（不持久化）
    abort_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        """持久化 / 对外可见的字段（不含运行时字段）。"""
        return {
            "task_id": self.task_id,
            "novel_id": self.novel_id,
            "kind": self.kind,
            "status": self.status.value,
            "phase": self.phase,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
