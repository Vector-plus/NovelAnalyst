"""audit 节点 —— deepread 之后的质量审计 + issue 落盘 + 分流。

对应设计文档《03-核心图设计_索引生成.md》§2.2 N6 + 《04-prompt_审查.md》§1/§2。

三件事（对齐 04-prompt_审查.md §0.1）：
1. 调 AuditAnalyzeReActAgent 自主调用 5 类 F 类检查工具（LLM）。
2. 生成检查报告（落盘 ``_staging/audit/report.json``，含 repair_suggestion 供人工参考）。
3. 完成 issue 落盘（节点函数 · 确定性）：``local_id`` → 真实 ``issue-*``，按
   ``opened_at`` 分片写 ``quality/issues/block-*.json``，更新 issue 高水位。

分流（一期收窄）：
- 有 ``critical`` → ``phase="review_issues"``（interrupt 等待人工 fixed/skip/stop）。
- 无 ``critical`` → ``phase="done"``（derive 已推迟，直接结束）。

一期边界（见 index_builder/AGENT.md D7/D8）：
- **不实现自动修复**：``correct_safe_through`` / ``patch_record`` 依赖读原文定位，
  留二期；一期所有 issue 一律落盘，critical 交人工。
- **不实现 issue 状态流转**：open→resolved 留二期；``fixed`` 重审计会重复落盘
  issue（接受冗余，靠 audit_summary 反映最新情况）。
- **审计失败不静默成功**：LLM 审计失败（重试 2 次仍失败）或「有章节但无 committed」
  时，落 ``_staging/audit/error.json`` 诊断文件并抛异常，让 task 进入 ``failed``
  （error 可见）；不再降级为 ``done`` 伪装成「审计通过」。
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

from deerflow_simple.config import SimpleConfig
from deerflow_simple.index_builder.agents.audit_analyze_react import (
    build_audit_agent,
    build_audit_prompt,
)
from deerflow_simple.index_builder.agents.runner import run_agent_streaming
from deerflow_simple.index_builder.agents.schemas import AuditResult
from deerflow_simple.index_builder.services.fingerprint import json_bytes
from deerflow_simple.index_builder.services.id_allocator import IdAllocator
from deerflow_simple.index_builder.state import BuildState
from deerflow_simple.index_builder.tools.common import load_json

_AUDIT_AGENT_CACHE: dict[str, object] = {}
# 分片粒度与 skeleton._shard_chapters 一致（size=20）
_ISSUE_BLOCK_SIZE = 20


def _get_audit_agent(config: SimpleConfig, novel_root: str):
    if novel_root not in _AUDIT_AGENT_CACHE:
        _AUDIT_AGENT_CACHE[novel_root] = build_audit_agent(config, novel_root)
    return _AUDIT_AGENT_CACHE[novel_root]


def _parse_json(text: str) -> dict:
    text = (text or "").strip()
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        text = m.group(0)
    return json.loads(text)


def _max_committed_chapter(novel_root: str) -> int:
    root = Path(novel_root)
    max_ch = 0
    ledger_dir = root / "ledger" / "chapters"
    if not ledger_dir.is_dir():
        return 0
    for fname in sorted(ledger_dir.iterdir()):
        if not fname.name.startswith("ch-") or not fname.name.endswith(".json"):
            continue
        data = load_json(root, f"ledger/chapters/{fname.name}")
        if data and data.get("status") == "committed":
            ch = data.get("chapter_ref", {}).get("chapter_order", 0)
            max_ch = max(max_ch, ch)
    return max_ch


def _issue_block_index(opened_at: int) -> int:
    """按 opened_at 映射到 issue 分片块号（1 起），与 skeleton size=20 对齐。

    opened_at<=0（一期不读原文无法定位）默认落 block-0001。
    """
    if opened_at <= 0:
        return 1
    return math.ceil(opened_at / _ISSUE_BLOCK_SIZE)


def _write_report(novel_root: str, payload: dict) -> None:
    """落盘审计报告（含 repair_suggestion，供人工参考；不写入 issue 记录）。"""
    staging = Path(novel_root) / "_staging" / "audit"
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "report.json").write_bytes(json_bytes(payload))


def _write_audit_error(novel_root: str, message: str) -> None:
    """审计失败时落诊断文件（供排查；随后抛异常让 task 进入 failed）。"""
    staging = Path(novel_root) / "_staging" / "audit"
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "error.json").write_bytes(json_bytes({
        "error": message,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }))


def _persist_issues(novel_root: str, novel_id: str, issues: list) -> dict:
    """确定性落盘：local_id → issue-*，按 opened_at 分片 append 到 quality/issues/。

    issue 记录遵循 templates §8.3（不含 repair_suggestion）：
    {id, category, severity, opened_at, safe_through, updates[]}
    """
    if not issues:
        return {"issue_count": 0, "critical_count": 0, "warning_count": 0,
                "written_blocks": [], "real_ids": []}

    root = Path(novel_root)
    alloc = IdAllocator(novel_root, novel_id)
    real_ids = alloc.allocate("issue", len(issues))

    blocks: dict[int, list] = {}
    for i, iss in enumerate(issues):
        opened_at = iss.get("opened_at", 0) or 0
        record = {
            "id": real_ids[i],
            "category": iss.get("category", ""),
            "severity": iss.get("severity", "warning"),
            "opened_at": opened_at,
            "safe_through": iss.get("safe_through", 0) or 0,
            "updates": iss.get("updates", []),
        }
        blocks.setdefault(_issue_block_index(opened_at), []).append(record)

    written_blocks: list = []
    for block_index, records in sorted(blocks.items()):
        rel = f"quality/issues/block-{block_index:04d}.json"
        block = load_json(root, rel)
        if block is None:
            # skeleton 已初始化，此处兜底创建
            block = {
                "schema_version": "2.0",
                "novel_id": novel_id,
                "id": f"issues-block-{block_index:04d}",
                "kind": "issue_collection",
                "revision": 1,
                "safe_through": 0,
                "issues": [],
            }
        block["issues"].extend(records)
        block["revision"] = block.get("revision", 1) + 1
        block["safe_through"] = max(block.get("safe_through", 0),
                                    max(r["opened_at"] for r in records))
        (root / rel).write_bytes(json_bytes(block))
        written_blocks.append(rel)

    critical_count = sum(1 for i in issues if i.get("severity") == "critical")
    return {"issue_count": len(issues),
            "critical_count": critical_count,
            "warning_count": len(issues) - critical_count,
            "written_blocks": written_blocks,
            "real_ids": real_ids}


def make_audit_node(config: SimpleConfig):
    """构造 audit 节点函数（闭包捕获 config）。"""

    async def audit_node(state: BuildState) -> BuildState:
        novel_root = state["novel_root"]
        novel_id = state["novel_id"]
        source_version = state["source_version"]

        batch_start = 1
        batch_end = _max_committed_chapter(novel_root)

        # 空小说（total_chapters=0）→ 无可审计产物，合法地直接结束。
        if state.get("total_chapters", 0) == 0:
            return {"phase": "done", "halt_reason": None}

        # 有章节但无任何 committed：deepread 未产出，审计无法进行 → 报错（不静默成功）。
        if batch_end <= 0:
            raise RuntimeError(
                "audit: 无已 committed 章节（total_chapters>0 但 ledger 无 committed），"
                "deepread 疑似未产出，审计中止。请检查 deepread 执行结果后重新构建。"
            )

        agent = _get_audit_agent(config, novel_root)
        prompt = build_audit_prompt(novel_root, novel_id, source_version, batch_start, batch_end)

        # ① LLM 审计（整批重试 ≤2；失败不再静默降级为 done，而是抛异常让 task failed）
        payload = None
        last_error: Exception | None = None
        for _ in range(2):
            try:
                text = await run_agent_streaming(agent, prompt, config)
                payload = AuditResult.model_validate(_parse_json(text)).model_dump()
                break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                continue
        if payload is None:
            # 审计失败：质量验证未完成，不能当作「审计通过」静默 done。
            # 落诊断文件 + 抛异常 → runtime 捕获后置 task 为 failed（error 可见）。
            _write_audit_error(
                novel_root,
                f"AuditAnalyzeReActAgent 连续 2 次调用失败，最后错误: {last_error}",
            )
            raise RuntimeError(
                "audit: AuditAnalyzeReActAgent 连续 2 次调用失败，审计中止。"
                f"最后错误: {last_error}"
            )

        # ② 生成检查报告（含 repair_suggestion 供人工参考）
        _write_report(novel_root, payload)

        # ③ issue 落盘（确定性）
        persist = _persist_issues(novel_root, novel_id, payload.get("issues", []))

        phase = "review_issues" if persist["critical_count"] > 0 else "done"

        return {
            "phase": phase,
            "halt_reason": None,
            "metrics": {"audit_issue_count": persist["issue_count"]},
        }

    return audit_node
