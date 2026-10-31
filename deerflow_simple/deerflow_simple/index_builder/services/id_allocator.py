"""IdAllocator —— ID 高水位分配器（持久化到 ledger/id-state.json）。

对齐 templates §11.4 + 03 文档 §4.7（record 级幂等）。

关键约束：
- 命名空间高水位持久化在 ``ledger/id-state.json`` 的 ``high_watermarks``。
  skeleton 已初始化 10 个命名空间（char/fac/setting/ev/rel/emo/thread/
  claim/update/issue），本类与之对齐。
- 「先分配、后写文件」允许产生空号（03 §4.7：写文件失败空耗高水位可容忍），
  但**重跑已 committed 章节时不得重新 allocate**——该约束由 IndexWriter 入口
  读 ledger 保证，不在本类内（本类只负责单调递增分配）。
- deepread 单协程串行执行，本类不做跨进程文件锁；二期并发构建时再补。
"""

from __future__ import annotations

import json
from pathlib import Path

from deerflow_simple.index_builder.services.fingerprint import json_bytes

# 与 skeleton._init_skeleton 写入 ledger/id-state.json 的 high_watermarks 键一致。
NAMESPACES = [
    "char", "fac", "setting", "ev", "rel", "emo", "thread",
    "claim", "update", "issue",
]


class IdAllocator:
    """ID 高水位分配器。"""

    def __init__(self, novel_root: str, novel_id: str):
        self.root = Path(novel_root)
        self.novel_id = novel_id
        self.path = self.root / "ledger" / "id-state.json"
        self.state = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and "high_watermarks" in data:
                    return data
            except (json.JSONDecodeError, OSError):
                pass
        # 兜底：skeleton 未跑或文件损坏时重建空高水位。
        return {
            "schema_version": "2.0",
            "novel_id": self.novel_id,
            "id": "id-state",
            "kind": "id_state",
            "revision": 1,
            "safe_through": 0,
            "high_watermarks": {ns: 0 for ns in NAMESPACES},
            "pending_reservation": None,
        }

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(json_bytes(self.state))

    def allocate(self, namespace: str, count: int = 1) -> list[str]:
        """为 namespace 分配 count 个连续 ID，并立即持久化高水位。

        Raises:
            ValueError: namespace 非法或 count 为负。
        """
        if namespace not in NAMESPACES:
            raise ValueError(f"非法 ID 命名空间: {namespace!r}")
        if count < 0:
            raise ValueError(f"count 不能为负: {count}")
        if count == 0:
            return []
        base = int(self.state["high_watermarks"].get(namespace, 0))
        ids = [f"{namespace}-{base + i + 1:04d}" for i in range(count)]
        self.state["high_watermarks"][namespace] = base + count
        self._save()
        return ids

    def high_watermark(self, namespace: str) -> int:
        """读取当前高水位（不分配）。"""
        return int(self.state["high_watermarks"].get(namespace, 0))
