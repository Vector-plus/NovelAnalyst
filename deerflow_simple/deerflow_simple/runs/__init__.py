"""worker 协程管理 —— 从 DeerFlow 提炼的 run 生命周期管理核心。

对应 DeerFlow 的 `runtime/runs/`：准入（create_or_reject）、同线程串行
（wait_for_prior_finalizing）、启动屏障（try_start）、后台 worker 协程
（run_agent）与取消（cancel）。
"""

from deerflow_simple.runs.manager import (
    ConflictError,
    RunManager,
    UnsupportedStrategyError,
)
from deerflow_simple.runs.schemas import RunRecord, RunStartOutcome, RunStatus
from deerflow_simple.runs.worker import run_agent, submit_run, wait_run

__all__ = [
    "ConflictError",
    "UnsupportedStrategyError",
    "RunManager",
    "RunRecord",
    "RunStartOutcome",
    "RunStatus",
    "run_agent",
    "submit_run",
    "wait_run",
]
