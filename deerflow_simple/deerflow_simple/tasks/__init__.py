"""长任务运行时 —— 通用「任务 + SSE 进度 + 暂停/恢复」基础设施。

索引生成（index_builder）与未来的长解说任务共用本模块：task_id 维度、sqlite 持久化、
后台协程驱动 graph、事件队列供 SSE 订阅、Human-in-Loop interrupt 暂停/恢复。

与 ``runs``（对话 run）互补：runs 是「一条消息 → 一次 agent 消费」，秒~分钟级；
tasks 是「一个 task_id → 跨多次对话」，小时~天级。
"""

from deerflow_simple.tasks.manager import TaskManager
from deerflow_simple.tasks.schemas import TaskRecord, TaskStatus
from deerflow_simple.tasks.store import TaskStore

__all__ = [
    "TaskManager",
    "TaskStore",
    "TaskRecord",
    "TaskStatus",
]
