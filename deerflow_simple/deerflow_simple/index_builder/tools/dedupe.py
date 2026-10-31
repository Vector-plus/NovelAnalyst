"""C 类 · 去重复用工具（ChapterReActAgent 用，一期留桩）。

对应 03 文档 §5.4。决策 D5：内容级语义去重（③）一期放弃，本类工具保留接口但
返回 ``no_match``，由 IndexWriter 写入侧的 record_id 判重（②）兜底。二期再实现
真实语义去重（需维护已建 claim/event 的语义索引）。

留桩是**刻意**的：Agent 侧拿不到「已存在」提示，会倾向重复建档，但这是「冗余」
而非「错误」，audit 的 check_orphan_claims 可兜底发现。一期目标是跑通链路。
"""

from __future__ import annotations

import json
from typing import Optional

from langchain_core.tools import tool


def _no_match() -> str:
    return json.dumps({"status": "no_match", "refs": []}, ensure_ascii=False)


def build_dedupe_tools(novel_root: str) -> list:
    @tool
    def dedupe_claim(claim_draft: str, scope_refs: Optional[str] = None) -> str:
        """查找与给定陈述草稿等价、已存在的 Claim。命中返回已有 Ref，否则 no_match。

        参数:
            claim_draft: 陈述文本草稿。
            scope_refs: 限定查找范围的 Ref（可选）。
        """
        return _no_match()

    @tool
    def dedupe_event(event_draft: str) -> str:
        """查找与给定事件草稿等价、已存在的 Event。命中返回已有 Ref，否则 no_match。

        参数:
            event_draft: 事件标题/摘要草稿。
        """
        return _no_match()

    @tool
    def find_similar_relationship(subject_a_ref: str, subject_b_ref: str) -> str:
        """查找两个主体之间已存在的关系对。命中返回已有 Ref，否则 no_match。

        参数:
            subject_a_ref: 主体 A 引用。
            subject_b_ref: 主体 B 引用。
        """
        return _no_match()

    return [dedupe_claim, dedupe_event, find_similar_relationship]
