"""deepread 两个 Agent 的输出契约（Pydantic 兜底校验）。

决策 1（P2b）：沿用 create_agent 原语 + Pydantic 兜底校验。Agent 输出 JSON 文本，
节点函数（P2c）用本模块模型 ``model_validate`` 校验，失败则重试（≤2 次）。

采用「宽松建模」：仅顶层关键字段强类型 + ``extra='ignore'``，嵌套结构用 list/dict
宽松承接，避免 LLM 字段命名漂移导致整体校验失败。字段语义以《04-prompt_第二阶段
精读.md》§1.2 / §2.2 为准。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ChapterExtraction(BaseModel):
    """单章精读的结构化结果（ChapterReActAgent 提交契约）。"""

    model_config = ConfigDict(extra="ignore")

    chapter_order: int
    chapter_id: str
    stage_ref: dict = Field(default_factory=dict)
    new_events: list = Field(default_factory=list)
    appended_updates_to_existing_events: list = Field(default_factory=list)
    new_claims: list = Field(default_factory=list)
    new_character_candidates: list = Field(default_factory=list)
    new_faction_candidates: list = Field(default_factory=list)
    new_setting_candidates: list = Field(default_factory=list)
    identity_link_candidates: list = Field(default_factory=list)
    relationship_candidates: list = Field(default_factory=list)
    thread_update_candidates: list = Field(default_factory=list)
    chapter_summary_markdown: dict = Field(default_factory=dict)
    stage_buffer_appends: list = Field(default_factory=list)
    issue_candidates: list = Field(default_factory=list)
    warnings: list = Field(default_factory=list)


class StageCommitPayload(BaseModel):
    """stage 聚合的结构化结果（StageCommitReActAgent 提交契约）。"""

    model_config = ConfigDict(extra="ignore")

    stage_ref: dict = Field(default_factory=dict)
    stage_range: dict = Field(default_factory=dict)
    as_of: int | None = None
    arc_summary: dict = Field(default_factory=dict)
    character_stages: list = Field(default_factory=list)
    faction_stages: list = Field(default_factory=list)
    faction_landscape: dict = Field(default_factory=dict)
    relationship_snapshots: list = Field(default_factory=list)
    emotional_stages: list = Field(default_factory=list)
    thread_updates: list = Field(default_factory=list)
    warnings: list = Field(default_factory=list)
    notes_for_audit: list = Field(default_factory=list)


# ---------------------------------------------------------------------------
# audit（N6）输出契约 —— 对齐《04-prompt_审查.md》§1.2 schema
# ---------------------------------------------------------------------------
class AuditIssueUpdate(BaseModel):
    """issue 的单个更新片段（templates §8.3）。"""

    model_config = ConfigDict(extra="ignore")

    revealed_at: int | None = None
    status: str = "open"  # open（一期审计只新增 open）
    description: str = ""
    related_refs: list = Field(default_factory=list)
    source_refs: list = Field(default_factory=list)
    resolution_refs: list = Field(default_factory=list)


class RepairSuggestion(BaseModel):
    """修复建议（Agent → 分流层的中间产物，不写入 issue 记录）。"""

    model_config = ConfigDict(extra="ignore")

    auto_fixable: bool = False
    action: str = "manual"  # correct_safe_through / patch_record / manual
    detail: str = ""


class AuditIssue(BaseModel):
    """单条审计问题（Agent 侧含 local_id 与 repair_suggestion，落库时剥离）。"""

    model_config = ConfigDict(extra="ignore")

    local_id: str
    category: str = ""  # stale_source / source_locator / coverage_gap
    severity: str = "warning"  # critical / warning
    opened_at: int = 0
    safe_through: int = 0
    updates: list = Field(default_factory=list)
    repair_suggestion: dict = Field(default_factory=dict)


class AuditSummary(BaseModel):
    """审计汇总。"""

    model_config = ConfigDict(extra="ignore")

    candidate_count: int = 0
    confirmed_issue_count: int = 0
    critical_count: int = 0
    warning_count: int = 0
    overview: str = ""


class AuditResult(BaseModel):
    """AuditAnalyzeReActAgent 的提交契约（④ audit_summary + issues）。"""

    model_config = ConfigDict(extra="ignore")

    audit_summary: AuditSummary = Field(default_factory=AuditSummary)
    issues: list = Field(default_factory=list)
    warnings: list = Field(default_factory=list)