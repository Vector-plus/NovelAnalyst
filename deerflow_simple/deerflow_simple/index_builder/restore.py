"""断点恢复 —— 从落盘产物推断构建断点（resume/repair 模式的恢复入口）。

对应设计文档《03-核心图设计_索引生成.md》§4 中断恢复机制 + §2.2 N1 entry 职责
（② 读 ledger 恢复 phase ③ 读 manifest 恢复游标 ④ 校验 source_version）。

一期 checkpointer 用 InMemorySaver（进程重启即丢 graph 执行态），故「断点恢复」
不能依赖 checkpoint，而必须从**确定性落盘产物**推断：

- ``source/index.json``：skeleton 切块产物（``safe_through`` = total_chapters）。
- ``navigation/stage-plan.json``：prescan 合并产物（``stages`` 非空 = prescan 完成；
  ``status=confirmed`` = review_plan 已 approve）。
- ``ledger/chapters/*.json``：deepread 四态（committed = 本章完成）。
- ``_staging/audit/report.json``：audit 完成产物。

推断优先级：skeleton → prescan → review_plan → deepread → audit → review_issues → done，
每个阶段用「完成证据」判断是否已过，落到第一个未完成的阶段。

注意边界：``review_plan`` / ``review_issues`` 是 Human-in-Loop interrupt 点，resume 推断出
这两个 phase 时，graph 会重新 ``interrupt_before`` 挂起，等待人工重新决策（InMemorySaver
丢 checkpoint 后无法自动恢复决策，需用户重新 approve / fixed）。
"""

from __future__ import annotations

from pathlib import Path

from deerflow_simple.index_builder.tools.common import load_json, total_chapters


def _first_uncommitted_chapter(root: Path, total: int) -> int:
    """返回第一个未 committed 的章（deepread 的 cursor 起点）。

    遍历 ``ledger/chapters/*.json``，收集已 committed 章的 ``chapter_order``，
    从 1 开始找第一个不在集合中的章；全部 committed 返回 ``total + 1``（表示
    deepread 已完成）。
    """
    ledger_dir = root / "ledger" / "chapters"
    if not ledger_dir.is_dir():
        return 1

    committed: set[int] = set()
    for fname in ledger_dir.iterdir():
        if not fname.name.startswith("ch-") or not fname.name.endswith(".json"):
            continue
        data = load_json(root, f"ledger/chapters/{fname.name}")
        if data and data.get("status") == "committed":
            order = data.get("chapter_ref", {}).get("chapter_order", 0)
            if order > 0:
                committed.add(order)

    for order in range(1, total + 1):
        if order not in committed:
            return order
    return total + 1


def _has_any_committed(root: Path) -> bool:
    """判断 ledger 中是否存在任一 committed 章（deepread 是否已启动的权威信号）。

    与 ``stage-plan.json`` 的 ``status`` / ``stages`` 不同，ledger 是 deepread 的
    **直接产物**，更可靠：只要有一章 committed，就说明 deepread 已经启动过（而
    prescan / review_plan 必然已完成，否则 deepread 无从开始）。因此当 stage-plan
    被 skeleton 重置（draft + 空 stages）或丢失，但 ledger 仍有 committed 章时，
    restore 应据此推断 deepread 续跑，而非退回 prescan 重扫——否则会重跑 skeleton
    覆盖 stage-plan，进一步破坏数据（见 AGENT.md D16 补丁）。
    """
    ledger_dir = root / "ledger" / "chapters"
    if not ledger_dir.is_dir():
        return False
    for fname in ledger_dir.iterdir():
        if not fname.name.startswith("ch-") or not fname.name.endswith(".json"):
            continue
        data = load_json(root, f"ledger/chapters/{fname.name}")
        if data and data.get("status") == "committed":
            return True
    return False


def restore_build_state(novel_root: str, source_version: str) -> dict:
    """从落盘产物推断断点，返回 ``{phase, total_chapters, current_chapter}``。

    Raises:
        ValueError: ``source_version`` 与已构建索引不一致（原文已变化，resume 不适用）。
    """
    root = Path(novel_root)

    # ④ 校验 source_version 一致性（manifest 是 skeleton 产物，存在即已完成切块）
    manifest = load_json(root, "manifest.json")
    if manifest is not None:
        manifest_sv = manifest.get("source_version")
        if manifest_sv and manifest_sv != source_version:
            raise ValueError(
                f"source_version 不一致：请求 {source_version!r}，索引已构建为 "
                f"{manifest_sv!r}。原文版本已变化，resume 不适用，请改用 "
                "build_mode=full 重新构建。"
            )

    # ① total_chapters（skeleton 切块产物）
    total = total_chapters(novel_root)

    # ② skeleton 未完成：source/index.json 不存在（切块都没做，必须重跑）
    if not (root / "source" / "index.json").is_file():
        return {"phase": "skeleton", "total_chapters": 0, "current_chapter": None}

    # ③ audit 已完成：report.json 存在（audit 是最后阶段，优先判断）
    audit_report = load_json(root, "_staging/audit/report.json")
    if audit_report is not None:
        has_critical = any(
            iss.get("severity") == "critical"
            for iss in audit_report.get("issues", [])
        )
        if has_critical:
            return {"phase": "review_issues", "total_chapters": total, "current_chapter": None}
        return {"phase": "done", "total_chapters": total, "current_chapter": None}

    # ④ deepread 是否已跑：ledger 有 committed 章 = deepread 已启动。
    # 关键修复（D16 补丁）：ledger 是 deepread 的直接产物，比 stage-plan 更权威。
    # 当 stage-plan 被 skeleton 重置（draft + 空 stages）或丢失，但 ledger 已有
    # committed 章时，应据此推断 deepread 续跑，而非退回 prescan 重扫——否则会
    # 重跑 skeleton 覆盖 stage-plan，进一步破坏数据。
    if _has_any_committed(root):
        cursor = _first_uncommitted_chapter(root, total)
        if cursor > total:
            # 全部 committed → deepread 完成，待 audit
            return {"phase": "audit", "total_chapters": total, "current_chapter": None}
        return {"phase": "deepread", "total_chapters": total, "current_chapter": cursor}

    # ⑤ deepread 未跑 → 按 stage-plan 推断前置阶段
    stage_plan = load_json(root, "navigation/stage-plan.json")
    if stage_plan is None:
        # skeleton 切块完成但骨架未初始化（罕见中间态）→ 重跑 skeleton（幂等无害）
        return {"phase": "skeleton", "total_chapters": total, "current_chapter": None}

    stages = stage_plan.get("stages", [])

    # prescan 未完成：stage-plan 存在但 stages 为空（skeleton 的初始产物）
    if not stages:
        return {"phase": "prescan", "total_chapters": total, "current_chapter": None}

    # review_plan 未 approve：prescan 已合并但 status 仍 draft
    if stage_plan.get("status") != "confirmed":
        return {"phase": "review_plan", "total_chapters": total, "current_chapter": None}

    # confirmed 但无 committed 章（理论不该发生，防御性）→ deepread 从 1 开始
    return {"phase": "deepread", "total_chapters": total, "current_chapter": 1}
