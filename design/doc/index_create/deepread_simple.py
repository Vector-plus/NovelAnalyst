import json
import os
import re
from typing import Optional, TypedDict

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.constants import START, END
from langgraph.graph import StateGraph
from pydantic import BaseModel, ConfigDict, Field

from index_writer import IndexWriter

load_dotenv()

# ---------- 配置 ----------
# 默认沿用 prescan 的 novel_root；如需验证诛仙目录可设 DEEPREAD_NOVEL_ROOT=.../novel_xianni
NOVEL_ROOT = os.getenv(
    'DEEPREAD_NOVEL_ROOT',
    '/Users/wickfu/code/cls-ai/deer-flow/xianni_test/work_test/novel',
)
# 默认只精读前 N 章做验证（0 表示全书）；默认 10 章，恰好覆盖 stage-001 完整范围，可触发一次 stage 聚合
MAX_CHAPTERS = int(os.getenv('DEEPREAD_MAX_CHAPTERS', '69'))
# 写盘根目录：精读产物统一落到 _staging/deepread/（验证用，不污染正式索引目录）
STAGING_DIR = os.getenv('DEEPREAD_STAGING_DIR', '_staging/deepread')

model = init_chat_model(
    model_provider=os.getenv('TENCENT_PROVIDER', 'openai'),
    model=os.getenv('TENCENT_MODEL', 'deepseek-chat'),
    base_url=os.getenv('TENCENT_BASE_URL', 'https://api.deepseek.com/v1'),
    temperature=0.2,
    api_key=os.getenv('TENCENT_API_KEY'),
)


# ---------- 文件读取辅助 ----------
def _load(rel_path: str) -> dict:
    with open(os.path.join(NOVEL_ROOT, rel_path), encoding='utf-8') as f:
        return json.load(f)


def _read_text(rel_path: str) -> str:
    with open(os.path.join(NOVEL_ROOT, rel_path), encoding='utf-8') as f:
        return f.read()


# ---------- 章节 / 阶段 索引（懒加载缓存，确定性路径，不依赖 LLM） ----------
_chapter_index: Optional[dict] = None
_stage_by_chapter: Optional[dict] = None
_stages: Optional[list] = None


def _build_chapter_index() -> dict:
    """构建 chapter_order -> {chapter_id, path, title, paragraph_count, vol_id} 映射。"""
    global _chapter_index
    if _chapter_index is not None:
        return _chapter_index
    si = _load('source/index.json')
    mapping = {}
    for entry in si['entries']:
        vol_id = entry['target']['path'].split('/')[1]
        vol_index = _load(entry['target']['path'])
        for ch in vol_index['chapters']:
            mapping[ch['chapter_order']] = {
                'chapter_id': ch['id'],
                'path': ch['path'],
                'title': ch['title'],
                'paragraph_count': ch['paragraph_count'],
                'vol_id': vol_id,
            }
    _chapter_index = mapping
    return mapping


def _build_stage_index() -> tuple:
    """构建 chapter_order -> stage 映射，并返回 stage 列表。"""
    global _stage_by_chapter, _stages
    if _stage_by_chapter is not None and _stages is not None:
        return _stage_by_chapter, _stages
    sp = _load('navigation/stage-plan.json')
    by_chapter = {}
    stages = list(sp['stages'])
    for st in stages:
        for r in st['chapter_ranges']:
            for ch in range(r['start'], r['end'] + 1):
                by_chapter[ch] = st
    _stage_by_chapter, _stages = by_chapter, stages
    return by_chapter, stages


def total_chapters() -> int:
    si = _load('source/index.json')
    return si['scope']['chapter_ranges'][0]['end']


# ---------- A 类 · 原文读取工具 ----------
@tool
def read_source(chapter_order: int, para_start: Optional[int] = None, para_end: Optional[int] = None) -> str:
    """读取指定章节的原文正文，支持按段落范围截取。

    参数:
        chapter_order: 章节号（1 起）。
        para_start: 起始段落号（1 起，含），不传则从第 1 段开始。
        para_end: 结束段落号（1 起，含），不传则到末尾。

    返回:
        原文正文，前面附一行元信息（章节号、段落总数、本次返回范围）。
    """
    idx = _build_chapter_index()
    if chapter_order not in idx:
        return f'章节不存在: {chapter_order}'
    info = idx[chapter_order]
    content = _read_text(info['path'])
    # 段落规则：空行分隔（paragraph_rule=blank_line_separated）
    paras = [p.strip() for p in content.split('\n\n') if p.strip()]
    start = (para_start or 1) - 1
    end = (para_end or len(paras))
    seg = paras[start:end]
    header = (
        f'[ch-{chapter_order:06d} | 标题:{info["title"]} | 卷:{info["vol_id"]} | '
        f'总段落 {len(paras)} | 返回段落 {start + 1}~{min(end, len(paras))}]'
    )
    return header + '\n\n' + '\n\n'.join(seg)


@tool
def read_source_window(center_chapter: int, window: int = 2) -> str:
    """读取某章前后相邻章节的开头/结尾片段，用于核对跨章衔接。

    参数:
        center_chapter: 中心章节号。
        window: 前后各取多少章（默认 2）。

    返回:
        相邻章节的起止片段拼接文本。
    """
    idx = _build_chapter_index()
    parts = []
    for offset in range(-window, window + 1):
        ch = center_chapter + offset
        if ch < 1:
            continue
        if ch not in idx:
            parts.append(f'--- 第{ch}章：不存在 ---')
            continue
        content = _read_text(idx[ch]['path'])
        paras = [p.strip() for p in content.split('\n\n') if p.strip()]
        head = '\n'.join(paras[:3])
        tail = '\n'.join(paras[-2:]) if len(paras) > 3 else ''
        parts.append(f'=== 第{ch}章 开头 ===\n{head}\n=== 第{ch}章 结尾 ===\n{tail}')
    return '\n\n'.join(parts)


# ---------- B 类 · 实体解析工具 ----------
@tool
def resolve_name(name: str, context_hint: Optional[str] = None) -> str:
    """将人物名字解析为已有实体 Ref（含候选）。命中唯一实体才返回 Ref，多候选/无命中返回提示。

    参数:
        name: 人物名字（如 '张小凡'）。
        context_hint: 可选上下文线索（如出场章节/身份），帮助消歧。

    返回:
        JSON 字符串：{\"status\": \"unique\"/\"multiple\"/\"no_match\", \"refs\": [...]}
    """
    # 已建档实体（characters/index.json 的 entries）
    try:
        char_idx = _load('characters/index.json')
    except Exception:
        char_idx = {'entries': []}
    hits = []
    for entry in char_idx.get('entries', []):
        # entry 形如 {target: {path, record_id}, label?}
        label = entry.get('label') or entry.get('title') or ''
        if label == name:
            hits.append(entry.get('target', entry))
    if len(hits) == 1:
        return json.dumps({'status': 'unique', 'refs': hits}, ensure_ascii=False)
    if len(hits) > 1:
        return json.dumps({'status': 'multiple', 'refs': hits}, ensure_ascii=False)
    return json.dumps({'status': 'no_match', 'refs': []}, ensure_ascii=False)


@tool
def fetch_entity_current(entity_ref: str) -> str:
    """读取实体 index.json 的 current 摘要（label、current_summary、identity_notes）。

    参数:
        entity_ref: 实体引用，形如 'characters/char-0001/index.json' 或 JSON 字符串 {\"path\":..., \"record_id\":...}。

    返回:
        实体 current 片段原始 JSON。
    """
    path = _parse_ref_path(entity_ref)
    if not path or not os.path.isfile(os.path.join(NOVEL_ROOT, path)):
        return f'实体不存在: {entity_ref}'
    data = _load(path)
    current = data.get('current', data)
    return json.dumps(current, ensure_ascii=False)


@tool
def lookup_stage(chapter_order: int) -> str:
    """查询某章落在哪个 stage（阶段骨架）。

    参数:
        chapter_order: 章节号。

    返回:
        JSON 字符串：该章所属 stage 的 id、title、chapter_ranges。
    """
    by_chapter, _ = _build_stage_index()
    if chapter_order not in by_chapter:
        return json.dumps({'status': 'no_stage', 'chapter_order': chapter_order}, ensure_ascii=False)
    st = by_chapter[chapter_order]
    return json.dumps({
        'status': 'ok',
        'stage_id': st['id'],
        'title': st['title'],
        'chapter_ranges': st['chapter_ranges'],
    }, ensure_ascii=False)


# ---------- C 类 · 去重复用工具 ----------
@tool
def dedupe_claim(claim_draft: str, scope_refs: Optional[str] = None) -> str:
    """查找与给定陈述草稿等价、已存在的 Claim。命中返回已有 Ref，否则返回 no_match。

    参数:
        claim_draft: 陈述文本草稿。
        scope_refs: 限定查找范围的 Ref（可选）。

    返回:
        JSON 字符串：{\"status\": \"hit\"/\"no_match\", \"refs\": [...]}
    """
    return json.dumps({'status': 'no_match', 'refs': []}, ensure_ascii=False)


@tool
def dedupe_event(event_draft: str) -> str:
    """查找与给定事件草稿等价、已存在的 Event。命中返回已有 Ref，否则返回 no_match。

    参数:
        event_draft: 事件标题/摘要草稿。

    返回:
        JSON 字符串：{\"status\": \"hit\"/\"no_match\", \"refs\": [...]}
    """
    return json.dumps({'status': 'no_match', 'refs': []}, ensure_ascii=False)


@tool
def find_similar_relationship(subject_a_ref: str, subject_b_ref: str) -> str:
    """查找两个主体之间已存在的关系对。

    参数:
        subject_a_ref: 主体 A 引用。
        subject_b_ref: 主体 B 引用。

    返回:
        JSON 字符串：{\"status\": \"hit\"/\"no_match\", \"refs\": [...]}
    """
    return json.dumps({'status': 'no_match', 'refs': []}, ensure_ascii=False)


# ---------- E 类 · 查询辅助工具（StageCommit 用） ----------
@tool
def fetch_entity_summary(entity_ref: str) -> str:
    """读取实体最新的 stage 摘要。

    参数:
        entity_ref: 实体引用。

    返回:
        实体最新 stage 摘要 JSON。
    """
    path = _parse_ref_path(entity_ref)
    if not path or not os.path.isfile(os.path.join(NOVEL_ROOT, path)):
        return f'实体不存在: {entity_ref}'
    data = _load(path)
    return json.dumps(data.get('current', data), ensure_ascii=False)


@tool
def fetch_event_detail(event_ref: str) -> str:
    """读取已存在事件的完整 updates 与 claims。

    参数:
        event_ref: 事件引用，形如 'events/block-0001.json'。

    返回:
        事件详情 JSON（当前索引为空时返回 no_match）。
    """
    path = _parse_ref_path(event_ref)
    if not path or not os.path.isfile(os.path.join(NOVEL_ROOT, path)):
        return f'事件不存在: {event_ref}'
    return json.dumps(_load(path), ensure_ascii=False)


@tool
def fetch_related_claims(subject_ref: str, chapter_range: Optional[str] = None) -> str:
    """读取与某主体相关的 claims。

    参数:
        subject_ref: 主体引用。
        chapter_range: 可选章节范围。

    返回:
        相关 claims 列表 JSON。
    """
    return json.dumps({'claims': []}, ensure_ascii=False)


@tool
def list_entity_stages(entity_ref: str) -> str:
    """列出实体已有的 stage Markdown 文件（供新 stage 编号）。

    参数:
        entity_ref: 实体引用。

    返回:
        已有 stage 文件列表 JSON。
    """
    path = _parse_ref_path(entity_ref)
    if not path:
        return json.dumps({'stages': []}, ensure_ascii=False)
    stages_dir = os.path.join(os.path.dirname(path), 'stages')
    full = os.path.join(NOVEL_ROOT, stages_dir)
    stages = []
    if os.path.isdir(full):
        stages = sorted(os.listdir(full))
    return json.dumps({'stages': stages}, ensure_ascii=False)


def _parse_ref_path(entity_ref: str) -> Optional[str]:
    """从实体引用中解析出相对 novel_root 的文件路径。"""
    if not entity_ref:
        return None
    if isinstance(entity_ref, str):
        s = entity_ref.strip()
        if s.startswith('{'):
            try:
                obj = json.loads(s)
                return obj.get('path')
            except Exception:
                return None
        # 形如 'characters/char-0001/index.json' 或 'char-0001'
        if s.endswith('index.json'):
            return s
        # 尝试按 record_id 推导（简化：直接当目录 index.json）
        if '/' not in s and s.startswith('char-'):
            return f'characters/{s}/index.json'
    return None


# ---------- 极简工具循环（对齐 prescan_simple.py） ----------
def _agent_loop(system: str, user: str, tools: list, max_rounds: int = 8, require_json: bool = True) -> str:
    model_with_tools = model.bind_tools(tools)
    msgs = [SystemMessage(content=system), HumanMessage(content=user)]
    tool_map = {t.name: t for t in tools}
    for _ in range(max_rounds):
        rsp = model_with_tools.invoke(msgs)
        msgs.append(rsp)
        if not rsp.tool_calls:
            content = rsp.content
            if require_json:
                try:
                    _extract_json(content)
                except Exception:
                    msgs.append(HumanMessage(
                        content='你刚才输出的不是合法 JSON（存在语法错误，如缺少逗号、引号未闭合、字符串内引号未转义等）。'
                                '请重新输出一个完整、合法的 JSON 对象，不要包含任何解释文字或 markdown 代码块。'
                    ))
                    continue
            return content
        for tc in rsp.tool_calls:
            fn = tool_map.get(tc['name'])
            out = fn.invoke(tc['args']) if fn else '未知工具'
            msgs.append(ToolMessage(content=str(out), tool_call_id=tc['id']))
    # 循环耗尽仍未收敛：强制模型停止调工具，直接输出最终 JSON
    msgs.append(HumanMessage(content='已收集足够信息，请立即停止调用工具，直接输出最终的 JSON 结果。'))
    for _ in range(2):
        content = model.invoke(msgs).content
        if not require_json:
            return content
        try:
            _extract_json(content)
            return content
        except Exception:
            msgs.append(HumanMessage(
                content='输出仍不是合法 JSON，请修复语法错误后重新输出完整 JSON。'
            ))
    return content


def _extract_json(text: str) -> dict:
    text = (text or '').strip()
    if text.startswith('\ufeff'):
        text = text[1:].strip()
    if text.startswith('```'):
        text = text.strip('`')
        if text.startswith('json'):
            text = text[4:]
    s = text.find('{')
    e = text.rfind('}')
    if s == -1 or e == -1:
        raise ValueError(f'未找到 JSON：{text[:200]}')
    raw = text[s:e + 1]
    candidates = [raw]
    candidates.append(re.sub(r',\s*([}\]])', r'\1', raw))
    candidates.append(re.sub(r'([}\]])\s*;\s*(?=[{\[])', r'\1, ', raw))
    t = re.sub(r',\s*([}\]])', r'\1', raw)
    candidates.append(re.sub(r'([}\]])\s*;\s*(?=[{\[])', r'\1, ', t))
    last_err = None
    for c in candidates:
        try:
            return json.loads(c)
        except json.JSONDecodeError as err:
            last_err = err
    pos = last_err.pos
    ctx = raw[max(0, pos - 80):pos + 80]
    raise ValueError(f'JSON 解析失败：{last_err.msg}\n出错位置附近：...{ctx}...')


# ---------- Pydantic 结构化输出模型（方案1：强制字段名对齐，消除 LLM 自由命名漂移） ----------
# 这些模型即「权威契约」：LLM 通过 tool-calling 以本 schema 提交结果，字段名不再漂移。
# 字段名综合了 04-prompt 文档规范性与 LLM 实际输出的合理性；核心字段强类型，易变字段宽松（dict）。

class _Base(BaseModel):
    model_config = ConfigDict(extra='ignore')  # 忽略 LLM 多出的字段，避免整体解析失败


class Ref(_Base):
    """实体/记录的引用。"""
    path: str
    record_id: Optional[str] = None


class ChapterRange(_Base):
    start: int
    end: int


class SourceRef(_Base):
    """Claim 的来源引用。"""
    path: str
    chapter_id: Optional[str] = None
    chapter_order: Optional[int] = None
    locator: Optional[dict] = None
    anchor: Optional[str] = None


class Claim(_Base):
    local_id: str
    text: str
    certainty: str = 'explicit'  # explicit / reported / inferred / uncertain
    attributed_to_candidate_or_ref: Optional[dict] = None
    revealed_at: int
    source_refs: list[SourceRef] = Field(default_factory=list)
    basis_refs: list[dict] = Field(default_factory=list)
    supersedes_refs: list[dict] = Field(default_factory=list)


class EventParticipant(_Base):
    entity_ref_or_candidate: dict  # {"candidate_name": ...} 或 {"path":..., "record_id":...}
    role: str = 'participant'


class EventUpdate(_Base):
    local_id: str
    chapter_ranges: list[ChapterRange] = Field(default_factory=list)
    revealed_at: Optional[int] = None
    status: str = 'ongoing'
    story_time: Optional[str] = None
    summary: str = ''
    participants: list[EventParticipant] = Field(default_factory=list)
    new_claim_local_ids: list[str] = Field(default_factory=list)
    trigger_claim_local_ids: list[str] = Field(default_factory=list)
    action_claim_local_ids: list[str] = Field(default_factory=list)
    outcome_claim_local_ids: list[str] = Field(default_factory=list)
    reused_claim_refs: list[dict] = Field(default_factory=list)
    related_event_refs: list[dict] = Field(default_factory=list)


class Event(_Base):
    local_id: str
    title: str
    introduced_at: int
    update: EventUpdate


class CharacterCandidate(_Base):
    # 字段名对齐模板 v2.0 entity_index：label / introduced_at
    label: str
    introduced_at: int
    alias_texts: list[str] = Field(default_factory=list)
    identity_notes: str = ''
    evidence_claim_local_ids: list[str] = Field(default_factory=list)


class SettingCandidate(_Base):
    # 字段名对齐模板 v2.0 setting：label / introduced_at
    label: str
    category: str = 'unknown'
    introduced_at: int
    notes: str = ''
    certainty: str = 'reported'
    evidence_claim_local_ids: list[str] = Field(default_factory=list)


class RelationshipCandidate(_Base):
    subject_a: dict  # {"candidate_name": ...} 或 {"path":..., "record_id":...}
    subject_b: dict
    facet: dict = Field(default_factory=dict)
    certainty: str = 'explicit'
    summary: str = ''
    source_claim_local_ids: list[str] = Field(default_factory=list)
    notes: str = ''


class SummaryFrontMatter(_Base):
    as_of: int
    stage_ref: dict = Field(default_factory=dict)
    subject_refs_or_candidates: list[dict] = Field(default_factory=list)
    record_refs_or_local_ids: list[str] = Field(default_factory=list)


class ChapterSummaryMarkdown(_Base):
    title: str
    front_matter: SummaryFrontMatter
    body_markdown: str


class ChapterExtraction(_Base):
    """单章精读的结构化结果（ChapterReActAgent 提交契约）。"""
    chapter_order: int
    chapter_id: str
    stage_ref: dict = Field(default_factory=dict)
    new_events: list[Event] = Field(default_factory=list)
    appended_updates_to_existing_events: list[dict] = Field(default_factory=list)
    new_claims: list[Claim] = Field(default_factory=list)
    new_character_candidates: list[CharacterCandidate] = Field(default_factory=list)
    new_faction_candidates: list[dict] = Field(default_factory=list)
    new_setting_candidates: list[SettingCandidate] = Field(default_factory=list)
    identity_link_candidates: list[dict] = Field(default_factory=list)
    relationship_candidates: list[RelationshipCandidate] = Field(default_factory=list)
    thread_update_candidates: list[dict] = Field(default_factory=list)
    chapter_summary_markdown: ChapterSummaryMarkdown
    stage_buffer_appends: list[dict] = Field(default_factory=list)
    issue_candidates: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class StageMarkdown(_Base):
    """stage 级 Markdown（front_matter + body）。"""
    front_matter: dict = Field(default_factory=dict)
    body_markdown: str = ''


class ArcSummary(_Base):
    """剧情阶段 arc 摘要。"""
    doc_id: str = ''
    front_matter: dict = Field(default_factory=dict)
    body_markdown: str = ''


class CharacterStage(_Base):
    """人物/势力阶段摘要（StageCommit 产出，字段对齐模板 v2.0）。"""
    candidate_name: str = ''
    entity_ref: dict = Field(default_factory=dict)  # Agent 猜测 ID，落库时以 candidate_name 重解析为准
    stage_doc_id: str = ''
    stage_markdown: StageMarkdown = Field(default_factory=StageMarkdown)
    current_summary_update: str = ''
    identity_notes_appends: list[dict] = Field(default_factory=list)


class RelationshipSnapshot(_Base):
    """关系阶段快照。"""
    relationship_ref_or_new: dict = Field(default_factory=dict)
    stage_doc_id: str = ''
    stage_markdown: StageMarkdown = Field(default_factory=StageMarkdown)
    facets: list[dict] = Field(default_factory=list)
    turning_event_refs: list[dict] = Field(default_factory=list)
    safe_through: Optional[int] = None


class EmotionalStage(_Base):
    """感情阶段分析。"""
    emotional_ref_or_new: dict = Field(default_factory=dict)
    new_assessment: dict = Field(default_factory=dict)
    stage_markdown: StageMarkdown = Field(default_factory=StageMarkdown)


class StageCommitPayload(_Base):
    """stage 聚合的结构化结果（StageCommitReActAgent 提交契约）。"""
    stage_ref: dict = Field(default_factory=dict)
    stage_range: dict = Field(default_factory=dict)
    as_of: int = Field(description='该 stage 的尾章号（等于 stage_range.end），是必填字段，用于 safe_through 与 revealed_at 上限')
    arc_summary: ArcSummary = Field(default_factory=ArcSummary)
    character_stages: list[CharacterStage] = Field(default_factory=list)
    faction_stages: list[CharacterStage] = Field(default_factory=list)
    faction_landscape: dict = Field(default_factory=dict)
    relationship_snapshots: list[RelationshipSnapshot] = Field(default_factory=list)
    emotional_stages: list[EmotionalStage] = Field(default_factory=list)
    thread_updates: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    notes_for_audit: list[str] = Field(default_factory=list)


def _structured_agent_loop(system: str, user: str, tools: list, output_model, max_rounds: int = 12):
    """ReAct 循环 + 结构化提交。

    把 Pydantic 模型绑定为「最终提交工具」：LLM 先自主调用只读工具收集信息，
    最后以 output_model 的 schema 提交结果。字段名被强制对齐到模型 schema，
    从根本上消除手写 JSON 解析时 LLM 自由命名导致的字段漂移。

    返回：output_model 的实例。
    """
    model_with_tools = model.bind_tools([*tools, output_model])
    msgs = [SystemMessage(content=system), HumanMessage(content=user)]
    tool_map = {t.name: t for t in tools}
    output_name = output_model.__name__

    for _ in range(max_rounds):
        rsp = model_with_tools.invoke(msgs)
        msgs.append(rsp)

        # 情况1：模型直接以文本输出 JSON（未走工具）
        if not rsp.tool_calls:
            content = (rsp.content or '').strip()
            if content:
                try:
                    return output_model.model_validate(_extract_json(content))
                except Exception:
                    pass
            msgs.append(HumanMessage(content='请调用提交工具，输出最终结构化结果。'))
            continue

        # 情况2：遍历工具调用。
        # 关键：为**每一个** tool_call 都生成 ToolMessage（含提交工具），
        # 保证 assistant 消息后的 ToolMessage 数量与 tool_call_id 一一对应，
        # 避免在同一轮混合「只读工具 + 提交工具」时，因提前 return 遗漏 ToolMessage
        # 而触发 OpenAI 兼容接口的 "insufficient tool messages" 校验错误。
        final_result = None
        for tc in rsp.tool_calls:
            name = tc['name']
            if name == output_name:
                # 最终提交：验证结果并暂存，但仍为该 tool_call 生成 ToolMessage
                try:
                    final_result = output_model.model_validate(tc['args'])
                    msgs.append(ToolMessage(
                        content='已接收最终结构化结果。',
                        tool_call_id=tc['id'],
                    ))
                except Exception as e:
                    msgs.append(ToolMessage(
                        content=f'提交解析失败：{e}。请检查字段后重新调用提交工具。',
                        tool_call_id=tc['id'],
                    ))
                continue
            fn = tool_map.get(name)
            out = fn.invoke(tc['args']) if fn else '未知工具'
            msgs.append(ToolMessage(content=str(out), tool_call_id=tc['id']))

        # 本轮流内所有 tool_call 都已生成 ToolMessage，消息序列完整，此时才返回结果
        if final_result is not None:
            return final_result

    # 循环耗尽：强制提交（多轮尝试 + 异常兜底，避免模型返回空/传空参数时
    # pydantic 原始校验错误（如 "as_of Field required"）直接向上传播）
    msgs.append(HumanMessage(content='信息已收集足够，请立即调用提交工具输出最终结构化结果。'))
    for _ in range(3):
        rsp = model.bind_tools([output_model]).invoke(msgs)
        msgs.append(rsp)
        if not rsp.tool_calls:
            # 模型未走工具，直接输出文本 JSON
            try:
                return output_model.model_validate(_extract_json(rsp.content or '{}'))
            except Exception as e:
                msgs.append(HumanMessage(
                    content=f'输出解析失败：{e}。请直接调用提交工具，并完整填写所有必填字段。'
                ))
                continue
        for tc in rsp.tool_calls:
            if tc['name'] == output_name:
                try:
                    return output_model.model_validate(tc['args'])
                except Exception as e:
                    msgs.append(ToolMessage(
                        content=f'提交解析失败：{e}。请重新调用提交工具，完整填写所有必填字段（不要传空参数）。',
                        tool_call_id=tc['id'],
                    ))
            else:
                fn = tool_map.get(tc['name'])
                out = fn.invoke(tc['args']) if fn else '未知工具'
                msgs.append(ToolMessage(content=str(out), tool_call_id=tc['id']))
    # 最终兜底：抛出清晰错误，便于上层识别为「提交失败」而非原始 pydantic 校验错误
    raise RuntimeError(
        f'{output_name} 结构化提交失败：模型多次尝试后仍未输出合法结果，'
        '请检查提交工具的必填字段是否缺失（如 as_of 等）。'
    )


# ---------- ① ChapterReActAgent · 单章精读 ----------
# 模块级常量，禁止任何插值，保证前缀缓存逐字节稳定（04-prompt §0.4）
CHAPTER_SYSTEM = """你是「单章精读分析员」。你的任务是对一章原文做结构化事实提取，产出一份供下游写入服务应用的 `ChapterExtraction` JSON。

## 你的工作原则

1. **你是提取员，不是作家。**
   - 只提取原文**明确发生**或**明确被某人说出**的事实，不做文学解读、不做情感定性、不做结局预测
   - 一切结论都要能对应到具体原文段落
   - 禁止凭借常识、同类小说套路补齐原文没说的内容

2. **你不写文件。** 你只输出 JSON。写盘由节点函数的确定性路径执行。

3. **严格遵守 certainty 四态语义**
   - `explicit`：原文叙述直接发生的动作、对话、场景变化。例如：「沈岚把口诀交给林舟」
   - `reported`：**任何角色说出口**的内容，无论听起来多么权威。例如：「沈岚自称来自青竹书院」
     - **特别警告**：角色说"我是 XX"、"我们宗门有 YY 规则"、"这个功法需要 ZZ"，这些**全部**是 reported，不是 explicit
   - `inferred`：解析归纳的内容，必须显式写出 `basis_refs` 或 `source_refs` 作为依据
   - `uncertain`：依据不足或多种理解并存，不要用概率数字替代

4. **身份谨慎原则**
   - 名字 → Ref：先调 `resolve_name` 查询。返回**唯一命中**才用该 Ref；返回**多候选**或**无命中**时，建立**临时实体候选**（在 `new_character_candidates` 中登记）
   - 禁止擅自把化名、绰号、黑衣人等合并到已知角色，即使你从后文知道答案也不行
   - 疑似同一人但当章未明示 → 作为**候选**记录在 `identity_link_candidates`，不要直接改引用

5. **关键结论必须带 anchor**
   - 身份揭示、重大反转、关系定性、能力首次展示 → `source_refs[].anchor` 必填（原文短片段，须在章内唯一匹配）
   - 普通叙述只填 `chapter_id/chapter_order` 即可，不强求 anchor
   - 没找到可靠 anchor 时**不要编造**，改为登记 `issue_candidates`（category=`missing_evidence`）

6. **去重复用，不要重复建档**
   - 新 Claim 产出前先调 `dedupe_claim`（给出 claim_draft + scope_refs），命中则在 `reused_claim_refs` 中引用，不再新建
   - 新 Event 产出前先调 `dedupe_event`，命中则作为该事件的新 `update` 追加，不新建 `ev-*`
   - 关系对出现前先调 `find_similar_relationship`，命中则后续归到既有 `rel-*` 下，仅输出 `relationship_update_candidates`

7. **章节摘要只组织已提取事实**
   - `chapter_summary_markdown` 的 Front Matter 中 `record_refs` 列出的所有 `[[claim-xxx]]` / `[[ev-xxx]]` 必须在本次输出的 `new_claims` / `new_events` / `reused_*_refs` 中有定义或引用
   - 正文使用固定小节：**开始局面；关键行动；转折与新信息；本章结果；未决问题与补读入口**
   - 不编造未在证据中出现的情节

8. **感情定性不出口**
   - 章节输出中**禁止**出现 `romance` / `familial` 等感情类别的直接定性
   - 只提取**互动事实**（谁对谁做了什么、说了什么、表达了什么态度），感情定性由 StageCommit 阶段汇总判断

9. **stage_buffer 追加物**
   - 对于当前 stage 累积有价值的证据（关键事件 ref、关键陈述 ref、人物转折点、势力动向），在 `stage_buffer_appends` 中登记
   - buffer 只存 Ref 和轻量元数据，不复制事实正文

10. **工具调用预算**
    - `read_source` 本章 ≤ 2 次（原则上 1 次完整读）
    - `read_source_window` ≤ 1 次（仅当需要确认跨章衔接）
    - `resolve_name` 按新名字数量调用，命中后可复用结果
    - `dedupe_claim` 每条新 claim 调一次
    - 总工具调用 ≤ 20 次，超限则停下输出当前能确定的部分并在 `warnings` 中说明

## 目录与导航

- `source/vol-XXX/ch-NNNNNN.txt`：章节原文（通过 `read_source(chapter_order)` 读取）
- `navigation/stage-plan.json`：已 confirmed 的阶段骨架；用 `lookup_stage(chapter_order)` 查当前章归属
- `characters/*/index.json`、`factions/*/index.json`、`settings/entries/*.json`：已有实体档案
- 你**不能**直接读取 ledger / audits / benchmarks 等运行材料

## 工具清单

| 工具 | 用途 |
|---|---|
| `read_source(chapter_order, para_start?, para_end?)` | 读章节原文 |
| `read_source_window(center_chapter, window=2)` | 读相邻章节片段（仅跨章衔接存疑时用） |
| `resolve_name(name, context_hint?)` | 名字 → 候选 Ref 列表 |
| `fetch_entity_current(entity_ref)` | 读实体 current 摘要（label、current_summary、identity_notes） |
| `lookup_stage(chapter_order, subject_ref?)` | 查当前章在哪个 stage |
| `dedupe_claim(claim_draft, scope_refs)` | 查等价陈述 |
| `dedupe_event(event_draft)` | 查等价事件 |
| `find_similar_relationship(subject_a_ref, subject_b_ref)` | 查已有关系对 |

## 输出格式（结构化提交）

信息收集完毕后，**必须调用提交工具**（ChapterExtraction schema）输出最终结构化结果。字段名与类型以提交工具的 schema 为准，不要用自由命名的 JSON 文本。以下 JSON 仅为字段参考：

{
  "chapter_order": 42,
  "chapter_id": "ch-000042",
  "stage_ref": {"path": "navigation/stage-plan.json", "record_id": "stage-003"},
  "new_events": [
    {
      "local_id": "ev-local-1",
      "title": "外门考核开始",
      "introduced_at": 42,
      "update": {
        "local_id": "update-local-1",
        "chapter_ranges": [{"start": 42, "end": 42}],
        "revealed_at": 42,
        "status": "ongoing",
        "story_time": null,
        "summary": "宗门外门考核在演武场开启，弟子按序号抽签。",
        "participants": [
          {"entity_ref_or_candidate": {"candidate_name": "林舟", "role": "participant"}}
        ],
        "new_claim_local_ids": ["claim-local-1", "claim-local-2"],
        "trigger_claim_local_ids": [],
        "action_claim_local_ids": ["claim-local-1"],
        "outcome_claim_local_ids": [],
        "reused_claim_refs": [],
        "related_event_refs": []
      }
    }
  ],
  "appended_updates_to_existing_events": [],
  "new_claims": [
    {
      "local_id": "claim-local-1",
      "text": "林舟抽到第七号签。",
      "certainty": "explicit",
      "attributed_to_candidate_or_ref": null,
      "revealed_at": 42,
      "source_refs": [
        {"path": "source/vol-002/ch-000042.txt", "chapter_id": "ch-000042", "chapter_order": 42}
      ],
      "basis_refs": [],
      "supersedes_refs": []
    }
  ],
  "new_character_candidates": [],
  "new_faction_candidates": [],
  "new_setting_candidates": [],
  "identity_link_candidates": [],
  "relationship_candidates": [],
  "thread_update_candidates": [],
  "chapter_summary_markdown": {
    "title": "第42章：外门考核",
    "front_matter": {
      "as_of": 42,
      "stage_ref": {"path": "navigation/stage-plan.json", "record_id": "stage-003"},
      "subject_refs_or_candidates": [{"candidate_name": "林舟"}],
      "record_refs_or_local_ids": ["ev-local-1", "claim-local-1"]
    },
    "body_markdown": "## 开始局面\n...\n\n## 关键行动\n...\n\n## 转折与新信息\n...\n\n## 本章结果\n...\n\n## 未决问题与补读入口\n..."
  },
  "stage_buffer_appends": [],
  "issue_candidates": [],
  "warnings": []
}

### 字段说明

- `local_id`：仅本次输出内部引用，节点函数通过 ID 分配器替换为真实 ID（`ev-*`、`claim-*`、`update-*`）
- `attributed_to_candidate_or_ref` / `entity_ref_or_candidate` 支持两种形式：
  - 已知实体：`{"path": "...", "record_id": "..."}`
  - 新候选：`{"candidate_name": "姓名"}`
- `locator` 和 `anchor` 对关键结论必填
- `participants[].role` ∈ `initiator / participant / recipient / witness / affected / mentioned / unknown`
- `facet.type` ∈ `kinship / instruction / friendship / romance / cooperation / hostility / membership / other`
- `thread_update_candidates.category/status/role` 使用受控值
- `issue_candidates.category` ∈ `identity_ambiguity / fact_conflict / missing_evidence / source_locator / coverage_gap / stale_source`

## 禁止事项

- ❌ 不要输出 Markdown 代码块包裹的 JSON（除 chapter_summary_markdown.body_markdown 字段内部）
- ❌ 不要调用任何写入工具（不存在）
- ❌ 不要为任何角色说法填 `certainty=explicit`
- ❌ 不要凭借后文知识回填前文认知
- ❌ 不要擅自合并化名、绰号到已知实体
- ❌ 不要输出 `assessment` / 感情定性 / `romance` 维度（除非原文明示）
- ❌ 不要凭空编造锚点；锚点必须是原文中可唯一匹配的短片段
- ❌ 不要在 `new_claims` 中产出没有任何 `source_refs` 或 `basis_refs` 的陈述
- ❌ 不要在 `chapter_summary_markdown.body_markdown` 中出现 record_refs 外的 `[[xxx]]`"""

CHAPTER_TOOLS = [
    read_source, read_source_window, resolve_name, fetch_entity_current,
    lookup_stage, dedupe_claim, dedupe_event, find_similar_relationship,
]


def chapter_react(chapter_order: int, known_entities_digest: str = '') -> dict:
    """单章精读：调 ChapterReActAgent 产出 ChapterExtraction。"""
    idx = _build_chapter_index()
    by_chapter, _ = _build_stage_index()
    info = idx[chapter_order]
    stage = by_chapter.get(chapter_order, {})
    stage_id = stage.get('id', 'unknown')
    stage_ranges = stage.get('chapter_ranges', [{'start': chapter_order, 'end': chapter_order}])
    stage_start = stage_ranges[0]['start']
    stage_end = stage_ranges[-1]['end']
    position_in_stage = chapter_order - stage_start + 1
    stage_chapter_count = stage_end - stage_start + 1

    user = f"""【任务】对以下章节做结构化精读提取。

- novel_root: {NOVEL_ROOT}
- source_version: source-v1
- chapter_order: {chapter_order}
- chapter_id: {info['chapter_id']}
- stage_ref: {{"path": "navigation/stage-plan.json", "record_id": "{stage_id}"}}
- stage_range: {stage_start} ~ {stage_end}
- current_chapter_in_stage: {position_in_stage} / {stage_chapter_count}

【当前已知实体清单（stage-plan 中的 character_candidates 节选，仅作导航参考，不是已建档实体）】
{known_entities_digest or '（暂无）'}

请执行：
1. 调 `read_source(chapter_order)` 读本章完整正文
2. 必要时调 `read_source_window` 核对跨章衔接（仅当章首明显承接或章尾有悬念时）
3. 对本章新出现的名字调 `resolve_name` 查找
4. 对疑似已有陈述调 `dedupe_claim`，对疑似已有事件调 `dedupe_event`，对疑似已有关系对调 `find_similar_relationship`
5. 调用提交工具，以 ChapterExtraction 的 schema 输出最终结构化结果"""

    result = _structured_agent_loop(CHAPTER_SYSTEM, user, CHAPTER_TOOLS, ChapterExtraction, max_rounds=30)
    return result.model_dump()


# ---------- ② StageCommitReActAgent · stage 聚合 ----------
STAGE_COMMIT_SYSTEM = """你是「阶段聚合员」。你拿到一个 stage 内所有章节已提取的事件和陈述聚合（stage_buffer），需要产出该阶段的**人物阶段摘要、势力阶段摘要、关系阶段快照、感情阶段分析、剧情 arc 摘要**，供下游写入服务应用。

## 你的工作原则

1. **你是组织者，不是重新提取员。**
   - 输入已包含本阶段所有事件 Ref 和陈述 Ref，你不读原文、不新增 Claim
   - 你的工作是**挑选、组织、归纳**已有事实，产出 stage 级 Markdown 与关系快照
   - 需要原文细节时，调 `fetch_event_detail` 或 `fetch_related_claims` 读结构化记录；**不**调 `read_source`

2. **严格按 stage_ref 归属**
   - 本次产出的所有 Markdown Front Matter 中 `stage_ref` 必须是输入指定的 stage
   - `chapter_ranges` 必须完全落在该 stage 的 chapter_ranges 内
   - `as_of` 为该 stage 的尾章（输入提供）
   - **不要**跨 stage 回填或预测下一阶段

3. **人物/势力阶段摘要**
   - 只为**本阶段确有经历**的人物/势力产出阶段 Markdown
   - 一次性出场、只被提及、无实质经历的实体 → **跳过**，不生成空 stage
   - 正文使用固定小节（见 schema）；无材料的小节注明"本范围尚未提取到依据"，不编造

4. **感情阶段与 assessment**
   - 感情定性**只在此处产出**，但必须谨慎
   - 新增 `assessment` 时：
     - `category` 使用受控值：`romantic` / `familial` / `friendship` / `mixed` / `uncertain`
     - 原文无明示恋爱关系 → `category=uncertain` 或 `friendship`，**不要**用 `romantic`
     - `relationship_links` 必须非空，指向本次产出或已有的关系阶段快照
   - 感情阶段 Markdown 的 `source_refs=[]`，`record_refs` 只列 assessment 和关系阶段
   - 正文固定小节：**分析结论；变化解释；关系阶段引用；推断边界**
   - 一次道谢、一次保护行为**不**升级为恋爱定性

5. **关系阶段快照**
   - 每一对涉及的关系都产出一个 `stage` 快照（同一 rel 下的新 stage 条目）
   - `facets[].direction` 严格区分 `symmetric` / `directed`；directed 必须有 from_ref/to_ref
   - **两端态度不自动对称**：如果只有一方有表达，另一方 attitude 留空或不添加
   - `facets[].basis_refs` 必须非空，指向支持此维度的 claim
   - `turning_event_refs` 收本阶段关键转折事件

6. **实体档案 current_summary 更新**
   - 对每个产出 stage 的实体，附上 `current_summary` 更新草稿（label 不变，updated_summary 简述当前经历总结，供 index.json 更新）
   - 身份揭示、重要能力变化在 `identity_notes_appends` 中追加新 IdentityNote（引用已有 claim，不新建）

7. **剧情 arc 摘要**
   - 产出 `plot/arcs/arc-xxx.md`，固定小节：**阶段范围；起始局面；核心目标与冲突；关键转折；阶段结果；下一阶段承接与未决问题**
   - 只组织本 stage buffer 中的事件和陈述，不写进未发生内容

8. **safe_through 和 revealed_at**
   - 所有产出的 `safe_through` 不能超过 stage 尾章
   - 所有 `revealed_at` 不早于其依据 claim 的 revealed_at
   - 身份合并（`identity_links`）必须有具体 basis claim；只有候选→候选不能升为 confirmed

9. **工具调用预算**
   - `fetch_entity_current` 对每个涉及实体最多 1 次
   - `fetch_event_detail` 对关键转折事件按需调用，总 ≤ 10 次
   - `list_entity_stages` 每个实体 1 次（确认已有 stage 编号）
   - 总工具调用 ≤ 25 次

## 输入输出目录

- stage_buffer：从 `_staging/{stage_id}/*.buffer.jsonl` 聚合的事件/陈述/转折点 Ref 列表（上游打包成 JSON 结构传入）
- 已有实体档案：`characters/*/index.json`、`factions/*/index.json`、`emotions/*/index.json`、`relationships/pairs/*.json`
- 你不读原文、不改 ledger

## 工具清单

| 工具 | 用途 |
|---|---|
| `fetch_entity_current(entity_ref)` | 读实体 index.json 的 current 片段（label、current_summary） |
| `fetch_entity_summary(entity_ref)` | 读实体最新 stage 摘要 |
| `fetch_event_detail(event_ref)` | 读事件完整 updates 与 claims |
| `fetch_related_claims(subject_ref, chapter_range?)` | 读与某主体相关的 claims |
| `list_entity_stages(entity_ref)` | 列实体已有 stage Markdown（供新 stage 编号） |

## 输出格式（结构化提交）

信息收集完毕后，**必须调用提交工具**（StageCommitPayload schema）输出最终结构化结果。字段名与类型以提交工具的 schema 为准，不要用自由命名的 JSON 文本。以下 JSON 仅为字段参考：

{
  "stage_ref": {"path": "navigation/stage-plan.json", "record_id": "stage-003"},
  "stage_range": {"start": 85, "end": 128},
  "as_of": 128,
  "arc_summary": {
    "doc_id": "doc-arc-003",
    "front_matter": {
      "title": "外门试炼阶段",
      "chapter_ranges": [{"start": 85, "end": 128}],
      "as_of": 128,
      "subject_refs": [],
      "record_refs": [],
      "source_refs": []
    },
    "body_markdown": "## 阶段范围\n...\n\n## 起始局面\n...\n\n## 核心目标与冲突\n...\n\n## 关键转折\n...\n\n## 阶段结果\n...\n\n## 下一阶段承接与未决问题\n..."
  },
  "character_stages": [
    {
      "candidate_name": "林舟",
      "entity_ref": {"path": "characters/char-0001/index.json", "record_id": "char-0001"},
      "stage_doc_id": "doc-char-0001-stage-003",
      "stage_markdown": {
        "front_matter": {
          "title": "外门试炼阶段",
          "chapter_ranges": [{"start": 85, "end": 128}],
          "as_of": 128,
          "subject_refs": [],
          "record_refs": [],
          "source_refs": []
        },
        "body_markdown": "## 阶段起点\n...\n\n## 目标与动机\n...\n\n## 关键选择与经历\n...\n\n## 身份与能力变化\n...\n\n## 认知与性格表现\n...\n\n## 阶段终点\n...\n\n## 证据不足与补读入口\n..."
      },
      "current_summary_update": "...",
      "identity_notes_appends": []
    }
  ],
  "faction_stages": [],
  "faction_landscape": {"produce": false, "reason": ""},
  "relationship_snapshots": [],
  "emotional_stages": [],
  "thread_updates": [],
  "warnings": [],
  "notes_for_audit": []
}

### 字段说明

- `candidate_name`：**必填**，人物/势力的显示名。落库时以它做名字消解定位真实实体（`entity_ref` 里的 ID 是占位猜测，不可信，落库层会忽略并重解析）
- `arc_summary.doc_id`、`character_stages[].stage_doc_id` 等由节点函数通过 ID 分配器或固定命名得到；此处可留占位
- `relationship_ref_or_new` 支持：已有 `{"existing_ref": {...}}` 或新建 `{"new_rel": {"pair_names": ["甲", "乙"], "kind": "..."}}`；`pair_names` **必填**，落库层靠它解析真实实体
- `emotional_ref_or_new` 同上，新建 `{"new_emotion": {"pair_names": ["甲", "乙"], "label": "..."}}`
- `faction_landscape.produce=false` 时节点函数跳过生成格局 Markdown
- 所有 Markdown 中的 `[[xxx]]` 必须在 `record_refs` 中声明

## 禁止事项

- ❌ 不要调用 `read_source` 或任何原文读取（本阶段不接触原文）
- ❌ 不要产出新的 `Claim`（本阶段只组织已有陈述）
- ❌ 不要在 Markdown 中出现 record_refs 外的 `[[xxx]]`
- ❌ 不要把 `romance` 用于原文未明示的关系
- ❌ 不要让关系两端态度自动对称
- ❌ 不要为无实质经历的实体生成空 stage.md
- ❌ 不要让 safe_through 超过 stage 尾章
- ❌ 不要跨 stage 回填（如把本 stage 的转折归功到上一 stage）
- ❌ 不要修改 stage-plan 骨架（骨架已 confirmed，不可变）"""

STAGE_COMMIT_TOOLS = [
    fetch_entity_current, fetch_entity_summary, fetch_event_detail,
    fetch_related_claims, list_entity_stages,
]


def stage_commit_react(stage: dict, stage_buffer: list) -> dict:
    """stage 聚合：调 StageCommitReActAgent 产出 StageCommitPayload。"""
    stage_id = stage['id']
    stage_title = stage['title']
    ranges = stage['chapter_ranges']
    stage_start = ranges[0]['start']
    stage_end = ranges[-1]['end']

    user = f"""【任务】对以下 stage 做阶段聚合，产出 stage 级 Markdown 与关系/感情快照。

- novel_root: {NOVEL_ROOT}
- novel_meta: {{"novel_id": "wukon", "source_version": "source-v1", "total_chapters": {total_chapters()}}}
- stage_ref: {{"path": "navigation/stage-plan.json", "record_id": "{stage_id}"}}
- stage_title: {stage_title}
- stage_range: {stage_start} ~ {stage_end}
- as_of: {stage_end}

【stage_buffer（本阶段章节已提取的事件/陈述/转折点聚合）】
{json.dumps(stage_buffer, ensure_ascii=False, indent=2)}

请执行：
1. 从 stage_buffer 中识别哪些实体在本阶段**确有实质经历**（出现在多个关键事件 / 有身份变化 / 有重要选择）
2. 对确有经历的实体：
   - 调 `list_entity_stages` 查已有 stage 编号
   - 必要时调 `fetch_entity_current` 读 current_summary
   - 产出 character_stage / faction_stage Markdown
3. 对本阶段涉及的关系对：必要时调 `fetch_event_detail` 读关键事件，产出关系阶段快照
4. 对本阶段情感互动：判断是否够升为 assessment（谨慎用 romantic），产出 emotional_stage Markdown + assessment
5. 产出 arc_summary（本 stage 剧情总览）
6. 更新相关 story_thread
7. 调用提交工具，以 StageCommitPayload 的 schema 输出最终结构化结果"""

    result = _structured_agent_loop(STAGE_COMMIT_SYSTEM, user, STAGE_COMMIT_TOOLS, StageCommitPayload, max_rounds=30)
    return result.model_dump()


# ---------- ③ 确定性写盘（节点函数承担，Agent 不写文件） ----------
def _staging_path(rel: str) -> str:
    full = os.path.join(NOVEL_ROOT, STAGING_DIR, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    return full


def _write_chapter_extraction(chapter_order: int, result: dict) -> None:
    info = _build_chapter_index()[chapter_order]
    path = _staging_path(f'chapters/{info["chapter_id"]}.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


def _append_stage_buffer(stage_id: str, chapter_order: int, appends: list) -> None:
    if not appends:
        return
    path = _staging_path(f'stages/{stage_id}.buffer.jsonl')
    with open(path, 'a', encoding='utf-8') as f:
        for item in appends:
            item = dict(item)
            item.setdefault('chapter_order', chapter_order)
            f.write(json.dumps(item, ensure_ascii=False) + '\n')


def _load_stage_buffer(stage_id: str) -> list:
    path = os.path.join(NOVEL_ROOT, STAGING_DIR, f'stages/{stage_id}.buffer.jsonl')
    if not os.path.isfile(path):
        return []
    items = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def _write_stage_commit(stage_id: str, result: dict) -> None:
    path = _staging_path(f'stages/{stage_id}.commit.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


# ---------- ④ deepread 节点 ----------
def deepread_node(state: dict) -> dict:
    """逐章精读 + 边界章触发 stage 聚合。串行 while 循环（03 §2.2 N5）。"""
    total = total_chapters()
    limit = MAX_CHAPTERS if MAX_CHAPTERS > 0 else total
    limit = min(limit, total)
    by_chapter, stages = _build_stage_index()
    writer = IndexWriter(NOVEL_ROOT)  # 正式索引落库器（events/characters/plot/... ）

    # 已知实体摘要：从 stage-plan 的 character_candidates 提取（仅导航参考）
    try:
        sp = _load('navigation/stage-plan.json')
        candidates = sp.get('character_candidates', [])
        known_entities_digest = json.dumps(
            candidates[:50], ensure_ascii=False, indent=2
        )
    except Exception:
        known_entities_digest = ''

    error_count = 0
    committed_stages = []
    results = []

    for chapter_order in range(1, limit + 1):
        print(f'\n[chapter] 精读 ch-{chapter_order:06d} ...')

        # 1. 单章精读（失败重试 ≤2，对齐 04-prompt §3.3）
        result = None
        for attempt in range(4):
            try:
                result = chapter_react(chapter_order, known_entities_digest)
                break
            except Exception as e:
                print(f'  [retry {attempt + 1}] 章精读失败: {e}')
        if result is None:
            error_count += 1
            if error_count >= 3:
                return {'phase': 'audit', 'halt_reason': 'error_limit',
                        'results': results, 'stage_commits': committed_stages}
            continue

        results.append(result)

        # 2. 确定性路径：正式索引落库（events/characters/plot/relationships/settings/threads + 账本）
        try:
            writer.write_chapter(chapter_order, result)
        except Exception as e:
            print(f'  [warn] 落库失败 ch-{chapter_order:06d}: {e}')
        # 保留原始提取结果到 _staging 作调试参考
        _write_chapter_extraction(chapter_order, result)
        stage_id = by_chapter.get(chapter_order, {}).get('id', 'unknown')
        _append_stage_buffer(stage_id, chapter_order, result.get('stage_buffer_appends', []))

        # 3. 边界章触发 stage 聚合
        stage = by_chapter.get(chapter_order, {})
        stage_end = stage.get('chapter_ranges', [{'end': chapter_order}])[-1]['end']
        if chapter_order == stage_end:
            print(f'  [stage] 到达 {stage_id} 尾章，触发 stage 聚合 ...')
            buffer = _load_stage_buffer(stage_id)
            commit = None
            for attempt in range(2):
                try:
                    commit = stage_commit_react(stage, buffer)
                    break
                except Exception as e:
                    print(f'  [retry {attempt + 1}] stage 聚合失败: {e}')
            if commit is not None:
                try:
                    writer.write_stage_commit(stage, commit)
                except Exception as e:
                    print(f'  [warn] stage 落库失败 {stage_id}: {e}')
                _write_stage_commit(stage_id, commit)
                committed_stages.append(stage_id)
                print(f'  [stage] {stage_id} 聚合完成')

        error_count = 0

    phase = 'audit' if limit >= total else 'deepread'
    print(f'\n[done] 精读 {limit}/{total} 章，聚合 stage: {committed_stages}')
    return {'phase': phase, 'halt_reason': None,
            'results': results, 'stage_commits': committed_stages}


# ---------- Graph ----------
class DeepReadState(TypedDict):
    phase: str
    halt_reason: str
    results: list
    stage_commits: list


def build_graph():
    graph = StateGraph(DeepReadState)
    graph.add_node('deepread', deepread_node)
    graph.add_edge(START, 'deepread')
    graph.add_edge('deepread', END)
    return graph.compile()


if __name__ == '__main__':
    app = build_graph()
    final = app.invoke({'phase': 'deepread', 'halt_reason': None, 'results': [], 'stage_commits': []})
    print('\n================ deepread 结果 ================')
    print(f"phase: {final.get('phase')}")
    print(f"halt_reason: {final.get('halt_reason')}")
    print(f"已精读章数: {len(final.get('results', []))}")
    print(f"已聚合 stage: {final.get('stage_commits', [])}")
    print(f"写盘目录: {os.path.join(NOVEL_ROOT, STAGING_DIR)}")
