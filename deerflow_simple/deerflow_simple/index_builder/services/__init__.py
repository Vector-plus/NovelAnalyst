"""索引构建底层服务（ID 分配 / 名字索引 / 指纹）。

对应 03 文档 §5.9 的底层 Services 层。这些服务是确定性路径（非 LLM），由
IndexWriter / LedgerService 调用；ReAct Agent 不直接接触。
"""

from deerflow_simple.index_builder.services.id_allocator import IdAllocator, NAMESPACES
from deerflow_simple.index_builder.services.name_index import NameIndex, normalize_name

__all__ = [
    "IdAllocator",
    "NAMESPACES",
    "NameIndex",
    "normalize_name",
]
