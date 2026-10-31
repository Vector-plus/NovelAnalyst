"""索引生成模块 —— 解析工作流（索引生成）的 graph + 节点 + Agent。

对应设计文档《03-核心图设计_索引生成.md》。一期（P0+P1 最短链路）只落地：
skeleton（切块/骨架/分片/校验，零 LLM）→ prescan（单卷扫读 + 阶段合并）→
review_plan（Human-in-Loop interrupt）。

对外入口：
- ``build_index_graph(config)``：编译索引生成 StateGraph。
- ``build_initial_state(config, novel_id, ...)``：构造 graph 初始 state。

由 ``tasks`` 模块（通用长任务运行时）驱动执行；``novel_id`` 由代码注入，
graph 通过 ``resolve_novel_index_path`` 确定性映射到 index root。
"""

from deerflow_simple.index_builder.graph import build_index_graph, build_initial_state

__all__ = [
    "build_index_graph",
    "build_initial_state",
]
