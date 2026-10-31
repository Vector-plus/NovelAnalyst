"""review_plan 节点 —— Human-in-Loop 阶段计划审核（interrupt 载体）。

对应设计文档《03-核心图设计_索引生成.md》§2.2 N4。

实现方式：``interrupt_before=["review_plan"]``（graph 编译时指定）。graph 在进入
本节点前暂停并持久化 checkpoint；用户经 resume API 提交决策后，决策写入 state 的
``pending_human_decision`` 通道，本节点据此路由：
- ``approve``：把 stage-plan status 从 draft 推进为 confirmed，phase → deepread。
- ``reject``：不改 stage-plan，phase 退回 prescan（重新扫读）。

一期 deepread 未实现：approve 后 phase="deepread" 会由路由落到 END（done），
二期接入 deepread 节点后自然续跑，无需改本节点。
"""

from __future__ import annotations

import json
from pathlib import Path

from deerflow_simple.index_builder.state import BuildState


def review_plan_node(state: BuildState) -> BuildState:
    """读取人工决策并路由。

    决策来自 resume API 注入的 ``pending_human_decision``（形如
    ``{"decision": "approve"}`` / ``{"decision": "reject"}``）。
    """
    decision = state.get("pending_human_decision") or {}
    action = decision.get("decision")

    if action == "approve":
        # 把 stage-plan 冻结为 confirmed（确定性落盘）
        stage_plan_path = Path(state["novel_root"]) / "navigation" / "stage-plan.json"
        if stage_plan_path.exists():
            stage_plan = json.loads(stage_plan_path.read_text(encoding="utf-8"))
            stage_plan["status"] = "confirmed"
            stage_plan_path.write_text(
                json.dumps(stage_plan, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        # 只返回需要更新的字段（不展开整个 state，避免 errors 聚合字段重复累加）
        return {"phase": "deepread", "pending_human_decision": None}
    if action == "reject":
        return {"phase": "prescan", "pending_human_decision": None}
    # 无有效决策（理论上不会到达，interrupt 后才进入本节点）
    return {"phase": "review_plan"}
