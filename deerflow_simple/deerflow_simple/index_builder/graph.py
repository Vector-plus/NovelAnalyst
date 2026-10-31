"""索引生成 Graph —— 唯一的 StateGraph（星型路由 + interrupt）。

对应设计文档《03-核心图设计_索引生成.md》§2。

关键结构（星型路由）：
- START → entry → route → {skeleton | prescan | review_plan | deepread} → entry → ...
- ``phase`` 字段即整个流程的状态机；每个节点完成后都回到 entry 重新路由。
- ``interrupt_before=["review_plan"]``：在 review_plan 前暂停，等待人工决策。

已接入节点：skeleton / prescan / review_plan / deepread / audit / review_issues；
derive 推迟（路由落到 done）。
"""

from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from deerflow_simple.config import SimpleConfig
from deerflow_simple.index_builder.nodes.audit import make_audit_node
from deerflow_simple.index_builder.nodes.deepread import make_deepread_node
from deerflow_simple.index_builder.nodes.human_review_issues import human_review_issues_node
from deerflow_simple.index_builder.nodes.prescan import make_prescan_node
from deerflow_simple.index_builder.nodes.review_plan import review_plan_node
from deerflow_simple.index_builder.nodes.skeleton import skeleton_node
from deerflow_simple.index_builder.state import BuildState
from deerflow_simple.spaces.paths import resolve_novel_index_path, resolve_novel_path

# 原文相对 space root 的路径（与 spaces/manager.py::SOURCE_DIR / SOURCE_FILE 一致）
_SOURCE_DIR = "source"
_SOURCE_FILE = "novel.txt"

def _entry_node(state: BuildState) -> dict:
    """entry 节点：透传（phase 已由输入 payload 指定 / checkpoint 恢复）。

    设计文档 §2.2 N1 的完整职责（读 ledger 恢复游标、校验 source_version）属于
    deepread 阶段的前置，P2c 实现 deepread 主体时再补。
    """
    return {}

def _route(state: BuildState) -> str:
    """按 phase 路由到对应节点；未知/终态 phase 落到 END（done）。"""
    phase = state.get("phase")
    if phase in ("skeleton", "prescan", "review_plan", "deepread", "audit", "review_issues"):
        return phase
    return "done"  # derive / done 等未实现或终态阶段直接结束

def build_index_graph(config: SimpleConfig, checkpointer=None):
    """编译索引生成 StateGraph。

    Args:
        config: SimpleConfig（供 prescan / deepread 装配 ReAct Agent 时取模型）。
        checkpointer: LangGraph checkpointer；None 时用 InMemorySaver。
    """
    builder = StateGraph(BuildState)

    builder.add_node("entry", _entry_node)
    builder.add_node("skeleton", skeleton_node)
    builder.add_node("prescan", make_prescan_node(config))
    builder.add_node("review_plan", review_plan_node)
    builder.add_node("deepread", make_deepread_node(config))
    builder.add_node("audit", make_audit_node(config))
    builder.add_node("review_issues", human_review_issues_node)

    builder.add_edge(START, "entry")
    builder.add_conditional_edges(
        "entry",
        _route,
        {
            "skeleton": "skeleton",
            "prescan": "prescan",
            "review_plan": "review_plan",
            "deepread": "deepread",
            "audit": "audit",
            "review_issues": "review_issues",
            "done": END,
        },
    )
    builder.add_edge("skeleton", "entry")
    builder.add_edge("prescan", "entry")
    builder.add_edge("review_plan", "entry")
    builder.add_edge("deepread", "entry")
    builder.add_edge("audit", "entry")
    builder.add_edge("review_issues", "entry")

    return builder.compile(
        checkpointer=checkpointer or InMemorySaver(),
        interrupt_before=["review_plan", "review_issues"],
    )

def build_initial_state(
    config: SimpleConfig,
    novel_id: str,
    source_version: str = "source-v1",
    build_mode: str = "full",
) -> dict:
    """构造 graph 的初始 state（不含 task_id，由 TaskManager.start 注入）。

    - ``novel_root``：索引树根（index root）= space_root/novel。
    - ``source_file``：原文文件 = space_root/source/novel.txt。
    """
    index_root = resolve_novel_index_path(config, novel_id)
    space_root = resolve_novel_path(config, novel_id)
    source_file = space_root / _SOURCE_DIR / _SOURCE_FILE

    return {
        "novel_id": novel_id,
        "novel_root": str(index_root),
        "source_file": str(source_file),
        "source_version": source_version,
        "build_mode": build_mode,
        "phase": "skeleton",
        "total_chapters": 0,
        "current_chapter": None,
        "published_through": 0,
        "pending_human_decision": None,
        "halt_reason": None,
        "metrics": {},
        "errors": [],
        "audit_issues": [],
    }
