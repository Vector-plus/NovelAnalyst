"""小说空间模块 —— 空间元数据 + 沙箱目录 + 原文 CRUD（纯后端，无 LLM）。"""

from deerflow_simple.spaces.manager import (
    SpaceManager,
    SpaceNotFoundError,
)
from deerflow_simple.spaces.models import NovelSpace
from deerflow_simple.spaces.paths import (
    INDEX_DIR,
    RESULT_DIR,
    resolve_novel_index_path,
    resolve_novel_path,
    resolve_novel_result_path,
)
from deerflow_simple.spaces.store import SpaceStore

__all__ = [
    "NovelSpace",
    "SpaceStore",
    "SpaceManager",
    "SpaceNotFoundError",
    "resolve_novel_path",
    "resolve_novel_index_path",
    "resolve_novel_result_path",
    "INDEX_DIR",
    "RESULT_DIR",
]
