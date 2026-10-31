"""LedgerService —— 章节账本四态状态机（权威事实源）。

对齐 templates §11.5 + 03 文档 §4.3。

四态：prepared → extracted → applying → committed，任一中途可 → blocked。
每章一个 ``ledger/chapters/ch-XXXXXX.json``，是断点恢复与幂等的权威事实源：
- state（LangGraph checkpoint）丢了也没关系，ledger 决定本章该重跑还是跳过。
- 已 committed 章：跳过（不重读、不重分配、不重写）。
- applying 章：按 operations[*].expected_sha256 / result_sha256 逐目标比对，
  决定「未开始重跑 / 部分已应用 / blocked」。

一期边界（对应 03 §4.7 的工程实现阶段）：
- 落地四态状态机 + allocated_ids 复用 + 按章跳过（章节级/记录级幂等）。
  operations 的指纹 CAS 逐目标重放由 IndexWriter（P2c）落地时接入。
- 本类不做文件锁（deepread 单协程串行）；跨进程并发构建再补（templates §11.5
  一致性边界）。

指纹规范见 services/fingerprint.py。
"""

from __future__ import annotations

import json
from pathlib import Path

from deerflow_simple.index_builder.services.fingerprint import json_bytes

# 四态常量（templates §11.5）
STATUS_PREPARED = "prepared"
STATUS_EXTRACTED = "extracted"
STATUS_APPLYING = "applying"
STATUS_COMMITTED = "committed"
STATUS_BLOCKED = "blocked"

# 合法状态迁移表（03 §4.3 状态机）
_TRANSITIONS: dict[str, set[str]] = {
    STATUS_PREPARED: {STATUS_EXTRACTED, STATUS_BLOCKED},
    STATUS_EXTRACTED: {STATUS_APPLYING, STATUS_BLOCKED},
    STATUS_APPLYING: {STATUS_COMMITTED, STATUS_BLOCKED},
    STATUS_BLOCKED: {STATUS_PREPARED, STATUS_EXTRACTED, STATUS_APPLYING},
    STATUS_COMMITTED: set(),
}


def ledger_id(chapter_id: str) -> str:
    """章节 ID → 账本记录 ID（templates §11.5：账本根 ID 为 ledger-ch-XXXXXX）。"""
    return f"ledger-{chapter_id}"


class LedgerService:
    """章节账本四态状态机。"""

    def __init__(
        self,
        novel_root: str,
        novel_id: str,
        source_version: str,
        stage_plan_revision: int = 1,
    ):
        self.root = Path(novel_root)
        self.novel_id = novel_id
        self.source_version = source_version
        self.stage_plan_revision = stage_plan_revision
        self.ledger_dir = self.root / "ledger" / "chapters"

    # ------------------------------------------------------------------
    # 寻址
    # ------------------------------------------------------------------
    def _path(self, chapter_id: str) -> Path:
        return self.ledger_dir / f"{chapter_id}.json"

    # ------------------------------------------------------------------
    # 读
    # ------------------------------------------------------------------
    def load(self, chapter_id: str) -> dict | None:
        path = self._path(chapter_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except (json.JSONDecodeError, OSError):
            return None

    def get_status(self, chapter_id: str) -> str | None:
        data = self.load(chapter_id)
        return data.get("status") if data else None

    def is_committed(self, chapter_id: str) -> bool:
        return self.get_status(chapter_id) == STATUS_COMMITTED

    def allocated_ids(self, chapter_id: str) -> list[str]:
        data = self.load(chapter_id)
        return list(data.get("allocated_ids", [])) if data else []

    # ------------------------------------------------------------------
    # 写
    # ------------------------------------------------------------------
    def prepare(self, chapter_id: str, chapter_order: int) -> dict:
        """创建或复用 prepared 账本。

        record 级幂等关键（03 §4.7）：若已有账本，**保留 allocated_ids**（不得
        重新分配）；否则新建空 prepared 模板。
        """
        existing = self.load(chapter_id)
        if existing is not None:
            return existing  # 复用已分配的 ID，不重跑 LLM 前不重复 allocate

        ledger = {
            "schema_version": "2.0",
            "novel_id": self.novel_id,
            "id": ledger_id(chapter_id),
            "kind": "chapter_ledger",
            "revision": 1,
            "safe_through": 0,
            "chapter_ref": {"chapter_id": chapter_id, "chapter_order": chapter_order},
            "source_version": self.source_version,
            "stage_plan_revision": self.stage_plan_revision,
            "status": STATUS_PREPARED,
            "allocated_ids": [],
            "input_revisions": [],
            "extraction": None,
            "operations": [],
            "error": None,
        }
        self._save(chapter_id, ledger)
        return ledger

    def transition(
        self,
        chapter_id: str,
        from_status: str,
        to_status: str,
        error: str | None = None,
    ) -> dict:
        """状态迁移（带 CAS：当前状态必须等于 from_status）。

        Raises:
            RuntimeError: 账本不存在 / 当前状态与 from_status 不符 / 非法迁移。
        """
        ledger = self.load(chapter_id)
        if ledger is None:
            raise RuntimeError(f"账本不存在: {chapter_id}")
        current = ledger.get("status")
        if current != from_status:
            raise RuntimeError(
                f"账本 {chapter_id} 状态迁移冲突：期望 {from_status}，实际 {current}"
            )
        if to_status not in _TRANSITIONS.get(from_status, set()):
            raise RuntimeError(f"非法状态迁移: {from_status} -> {to_status}")

        ledger["status"] = to_status
        if error is not None:
            ledger["error"] = error
        elif to_status != STATUS_BLOCKED:
            ledger["error"] = None
        ledger["revision"] = ledger.get("revision", 1) + 1
        self._save(chapter_id, ledger)
        return ledger

    def commit(self, chapter_id: str) -> dict:
        """标记账本 committed（从 applying 迁移；已 committed 幂等返回）。"""
        status = self.get_status(chapter_id)
        if status == STATUS_COMMITTED:
            return self.load(chapter_id) or {}
        if status != STATUS_APPLYING:
            raise RuntimeError(
                f"账本 {chapter_id} 不能从 {status} 直接 committed（须经 applying）"
            )
        return self.transition(chapter_id, STATUS_APPLYING, STATUS_COMMITTED)

    def record_extraction(
        self,
        chapter_id: str,
        allocated_ids: list[str],
        summary: str,
        record_ids: list[str],
    ) -> dict:
        """记录提取结果（allocated_ids + extraction），状态推进到 extracted。

        幂等：账本已在 extracted/applying/blocked 时仅更新字段、重置到 extracted，
        不重复分配 ID。一期 ``operations`` 留空（指纹 CAS 逐目标重放推迟二期，
        见 index_builder/AGENT.md D5 / 二期待办）。

        Raises:
            RuntimeError: 账本不存在（须先 prepare）。
        """
        ledger = self.load(chapter_id)
        if ledger is None:
            raise RuntimeError(f"账本不存在: {chapter_id}（须先 prepare）")
        ledger["allocated_ids"] = list(allocated_ids)
        ledger["extraction"] = {
            "summary": summary,
            "record_ids": list(record_ids),
            "coverage_topics": {},
        }
        ledger["operations"] = []  # 一期留空
        ledger["status"] = STATUS_EXTRACTED
        ledger["error"] = None
        ledger["revision"] = ledger.get("revision", 1) + 1
        self._save(chapter_id, ledger)
        return ledger

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _save(self, chapter_id: str, ledger: dict) -> None:
        path = self._path(chapter_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(json_bytes(ledger))
