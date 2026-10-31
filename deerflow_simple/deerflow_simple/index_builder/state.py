"""索引生成 Graph 的 State 定义。

对应设计文档《03-核心图设计_索引生成.md》§3。P0+P1 只跑 skeleton → prescan →
review_plan；P2 接入 deepread；P3 接入 audit / review_issues（derive 推迟）。

核心原则（设计文档 §3.4）：
1. State 瘦身：只放「游标 + 控制信号 + 聚合结果」。
2. 聚合用 reducer（Annotated[list, add]），禁止手动 append。
3. 大对象不进 state：原文 / 抽取结果都落盘，state 只放路径与游标。
"""

from __future__ import annotations

from operator import add
from typing import Annotated, Literal, TypedDict

# 阶段枚举（skeleton/prescan/review_plan/deepread/audit/review_issues 已实现；
# derive 推迟，graph 未实现该节点，路由把 derive 落到 done）
Phase = Literal[
    "skeleton",
    "prescan",
    "review_plan",
    "deepread",
    "audit",
    "review_issues",
    "derive",
    "done",
]

class BuildState(TypedDict):
    """索引构建任务的 graph state。"""

    # ① 任务标识（不可变）
    task_id: str
    novel_id: str
    novel_root: str          # 索引树根（index root）绝对路径
    source_file: str         # 原文文件绝对路径（space_root/source/novel.txt）
    source_version: str

    # ② 构建模式
    build_mode: Literal["full", "resume", "repair"]

    # ③ 阶段控制（Graph 状态机，星型路由依据）
    phase: Phase

    # ④ 进度游标
    total_chapters: int
    current_chapter: int | None   # deepread 当前章（恢复起点；None=未开始/已结束）
    published_through: int        # 已连续发布前缀（deepread 每章后推进）

    # ⑤ Human-in-Loop 载荷（review_plan 决策）
    pending_human_decision: dict | None

    # ⑥ 聚合（reducer 累加）
    errors: Annotated[list, add]
    audit_issues: Annotated[list, add]  # audit 产出的 issue（一期由 quality/issues/ 落盘承载，此字段预留二期跨节点汇聚）

    # ⑦ 中断控制（deepread while 循环退出依据）
    halt_reason: str | None       # budget_exceeded / error_limit / io_error / None

    # ⑧ 可观测元数据
    metrics: dict                 # {chapters_processed, llm_calls, retry_count}
