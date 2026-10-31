"""Memory —— 长期记忆（事实抽取 + 检索 + 注入）。

对应 DeerFlow 的 `agents/memory/`，精简版保留 deermem 的核心机制：

- 结构化抽取：LLM 输出 JSON（content / category / confidence）。
- 纯寒暄过滤：丢弃「嗯 / 好的 / 谢谢」等确认语。
- 置信度阈值：低置信度事实不存。
- 去重：精确去重 + 包含关系合并。
- 容量驱逐：超出 max_facts 按 confidence 降序保留。
- 注入裁剪：按 confidence 降序取前 N 条。

简化点（学习项目）：不做 user/thread 隔离、不做 debounce、同步抽取。
"""

from deerflow_simple.memory.manager import SimpleMemoryManager, get_memory_manager

__all__ = ["SimpleMemoryManager", "get_memory_manager"]
