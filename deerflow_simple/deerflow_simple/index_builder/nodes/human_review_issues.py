"""human_review_issues 节点 —— N7 Human-in-Loop 问题审核（interrupt 载体）。

对应设计文档《03-核心图设计_索引生成.md》§2.2 N7。

实现方式：``interrupt_before=["review_issues"]``（graph 编译时指定）。graph 在进入
本节点前暂停并持久化 checkpoint；用户经 resume API 提交决策后，决策写入 state 的
``pending_human_decision`` 通道，本节点据此路由（对齐 review_plan_node 模式）：
- ``fixed``：重新审计（phase → audit），验证人工修复是否到位。
- ``skip``：跳过剩余问题，直接结束（derive 已推迟，一期 phase → done）。
- ``stop``：停止构建（phase → done）。

一期边界（见 index_builder/AGENT.md D8）：
- derive 节点彻底推迟，故 ``skip`` 直接落到 ``done``（不经过 derive）。
- 一期不实现 issue 状态流转（open→resolved），``fixed`` 重审计会重新落盘 issue
  （接受冗余，靠 audit_summary 反映最新情况）。
"""

from __future__ import annotations

from deerflow_simple.index_builder.state import BuildState


def human_review_issues_node(state: BuildState) -> BuildState:
    """读取人工决策（fixed/skip/stop）并路由。"""
    decision = state.get("pending_human_decision") or {}
    action = decision.get("decision")

    if action == "fixed":
        # 重新审计验证修复（phase 回 audit）
        return {"phase": "audit", "pending_human_decision": None}
    if action == "skip":
        # derive 推迟，直接结束
        return {"phase": "done", "pending_human_decision": None}
    if action == "stop":
        return {"phase": "done", "pending_human_decision": None}
    # 无有效决策（理论上不会到达，interrupt 后才进入本节点）
    return {"phase": "review_issues"}
