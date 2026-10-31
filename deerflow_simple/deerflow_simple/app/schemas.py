"""HTTP API 的请求 / 响应模型。

对应 DeerFlow 的 `app/gateway/run_models.py::RunCreateRequest` +
`thread_runs.py::RunResponse`。精简掉 assistant_id / checkpoint / stream_mode
等 LangGraph Platform 兼容字段，只保留 worker 协程管理所需的最小集合。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RunCreateRequest(BaseModel):
    """创建 run 的请求体。"""

    message: str = Field(..., min_length=1, description="用户消息")
    thread_id: str = Field(default="default", description="线程 ID，用于多轮记忆")
    multitask_strategy: Literal["reject", "interrupt", "rollback"] = Field(
        default="reject",
        description="同线程已有活跃 run 时的处理策略",
    )
    novel_id: str | None = Field(
        default=None,
        description="当前对话绑定的小说空间 id，供解说工具通过代码注入（不交给 LLM 决策）",
    )


class RunResponse(BaseModel):
    """单个 run 的响应体。"""

    run_id: str
    thread_id: str
    status: str
    multitask_strategy: str = "reject"
    error: str | None = None
    result: str | None = None
    created_at: str = ""
    updated_at: str = ""


class TaskCreateRequest(BaseModel):
    """创建长任务（索引生成等）的请求体。"""

    novel_id: str = Field(..., description="绑定的小说空间 id")
    kind: str = Field(default="index_build", description="任务类型")
    source_version: str = Field(default="source-v1", description="绑定的原文版本")
    build_mode: Literal["full", "resume", "repair"] = Field(default="full", description="构建模式")


class TaskResumeRequest(BaseModel):
    """恢复暂停任务的请求体（Human-in-Loop 决策）。"""

    decision: dict | None = Field(default=None, description="人工决策，如 {'decision': 'approve'}")


class TaskResponse(BaseModel):
    """单个长任务的响应体。

    ``status`` / ``phase`` 取值说明：

    ``status`` —— 任务生命周期状态（对齐 ``tasks.schemas.TaskStatus``）：
    | 取值 | 含义 |
    |---|---|
    | ``pending`` | 已创建，尚未开始执行 |
    | ``running`` | 正在执行 |
    | ``paused`` | 等待人工决策（Human-in-Loop interrupt） |
    | ``done`` | 正常完成 |
    | ``failed`` | 执行失败 |
    | ``cancelled`` | 已取消（手动取消 / 进程重启对账） |

    ``phase`` —— 当前 Graph 所处阶段（对齐 ``index_builder.state.Phase`` 星型路由）：
    | 取值 | 含义 |
    |---|---|
    | ``skeleton`` | 初始化索引骨架（切块/分片/校验） |
    | ``prescan`` | 粗读扫卷 + 阶段计划合并 |
    | ``review_plan`` | 等待人工审核阶段计划（interrupt 点） |
    | ``deepread`` | 逐章精读 + 阶段聚合 |
    | ``audit`` | 质量审计 |
    | ``review_issues`` | 等待人工审核审计问题（interrupt 点） |
    | ``done`` | 完成 |
    """

    task_id: str
    novel_id: str
    kind: str
    status: str = Field(
        description="任务生命周期状态：pending / running / paused / done / failed / cancelled"
    )
    phase: str = Field(
        default="",
        description=(
            "当前 Graph 阶段：skeleton / prescan / review_plan / deepread / audit / "
            "review_issues / derive（一期推迟）/ done"
        ),
    )
    error: str | None = None
    created_at: str = ""
    updated_at: str = ""
