"""audit 节点简易验证脚本。

对齐《03-核心图设计.md》N6 audit 与《04-prompt_审查.md》v0.1：
    - 5 类确定性检查工具（F 类 · 只读，不依赖 LLM）
    - AuditAnalyzeReActAgent 自主调用检查工具，汇总结果、判定 severity/category、
      生成 human-readable 的 issue 描述与审计汇总（一期：不读原文）
    - 确定性写盘到 _staging/audit/（验证用，不污染正式索引）

数据源（novel/ 目录）：
    manifest.json                   小说元信息
    ledger/id-state.json            ID 高水位
    ledger/chapters/ch-*.json       章账本（四态）
    navigation/stage-plan.json      阶段骨架
    各主题 index.json + block-*.json 索引产物
"""
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

load_dotenv()

# ---------- 配置 ----------
NOVEL_ROOT = os.getenv(
    'AUDIT_NOVEL_ROOT',
    '/Users/wickfu/code/cls-ai/deer-flow/xianni_test/work_test/novel',
)
# 审计报告落盘根目录（验证用，不污染正式 quality/ 索引）
STAGING_DIR = os.getenv('AUDIT_STAGING_DIR', '_staging/audit')

model = init_chat_model(
    model_provider=os.getenv('DEEPSEEK_PROVIDER', 'openai'),
    model=os.getenv('DEEPSEEK_MODEL', 'deepseek-chat'),
    base_url=os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com/v1'),
    temperature=0.2,
    api_key=os.getenv('DEEPSEEK_API_KEY'),
)


# ---------- 文件读取辅助 ----------
def _load(rel_path: str) -> Optional[dict]:
    full = os.path.join(NOVEL_ROOT, rel_path)
    if not os.path.isfile(full):
        return None
    with open(full, encoding='utf-8') as f:
        return json.load(f)


def _read_text(rel_path: str) -> str:
    with open(os.path.join(NOVEL_ROOT, rel_path), encoding='utf-8') as f:
        return f.read()


def _max_committed_chapter() -> int:
    """从 ledger 推断已 committed 的最大章号（check_stage_integrity 用）。"""
    max_ch = 0
    ledger_dir = os.path.join(NOVEL_ROOT, 'ledger', 'chapters')
    if not os.path.isdir(ledger_dir):
        return max_ch
    for fname in os.listdir(ledger_dir):
        if not fname.startswith('ch-') or not fname.endswith('.json'):
            continue
        data = _load(f'ledger/chapters/{fname}')
        if data and data.get('status') == 'committed':
            ch = data.get('chapter_ref', {}).get('chapter_order', 0)
            max_ch = max(max_ch, ch)
    return max_ch


def _iter_event_blocks():
    """迭代 events/ 下的 block-*.json 文件相对路径。"""
    events_dir = os.path.join(NOVEL_ROOT, 'events')
    if not os.path.isdir(events_dir):
        return
    for fname in sorted(os.listdir(events_dir)):
        if fname.startswith('block-') and fname.endswith('.json'):
            yield f'events/{fname}'


# ---------- F 类 · 审计检查工具（确定性 · 只读 · 不依赖 LLM） ----------
# 每个工具返回 JSON 字符串，结构：{"check": ..., "hit_count": N, "hits": [...]}
# hit 统一含 record_ref（定位）+ problem（机器可读问题描述）+ 可选上下文字段。

# check_ref_reachability 需要扫描的根索引文件（其 entries[].target / entity_refs 是主要 Ref 来源）
_ROOT_INDEX_FILES = [
    'characters/index.json',
    'events/index.json',
    'relationships/index.json',
    'emotions/index.json',
    'factions/index.json',
    'plot/index.json',
    'settings/index.json',
    'threads/index.json',
    'quality/issues.json',
    'quality/coverage.json',
    'navigation/catalog.json',
    'navigation/chapters/index.json',
    'navigation/names/index.json',
    'navigation/task-routes.json',
]


def _check_ref(ref: dict, src: str, acc: list) -> None:
    """校验单个 Ref 的 path 可达 + record_id 可达，不可达则追加到 acc。"""
    if not isinstance(ref, dict):
        return
    path = ref.get('path')
    if not path:
        return
    record_id = ref.get('record_id')
    full = os.path.join(NOVEL_ROOT, path)
    if not os.path.isfile(full):
        acc.append({'record_ref': ref, 'from': src, 'problem': f'path 文件不存在: {path}'})
        return
    # 原文引用（source/ 开头）只校验 path 存在，不校验 record_id
    if record_id and not path.startswith('source/'):
        content = _read_text(path)
        if record_id not in content:
            acc.append({'record_ref': ref, 'from': src,
                        'problem': f'record_id "{record_id}" 不在目标文件 {path} 中'})


@tool
def check_ref_reachability() -> str:
    """校验索引产物中所有 Ref 的 path 可达 + record_id 可达，返回不可达清单。

    返回 JSON 字符串：{"check": "check_ref_reachability", "hit_count": N, "hits": [...]}
    每个 hit 含 record_ref、from（引用来源文件）、problem。
    """
    unreachable = []
    # 1. 各根索引文件的 entries[].target / entity_refs
    for rel in _ROOT_INDEX_FILES:
        idx = _load(rel)
        if not idx:
            continue
        for e in idx.get('entries', []):
            _check_ref(e.get('target', {}), rel, unreachable)
            for r in e.get('entity_refs', []):
                _check_ref(r, rel, unreachable)
    # 2. manifest 中的各类 *_ref
    manifest = _load('manifest.json')
    if manifest:
        for key, val in manifest.items():
            if isinstance(val, dict) and 'path' in val:
                _check_ref(val, 'manifest.json', unreachable)
    # 3. events block 中的实体引用与跨记录引用
    for rel in _iter_event_blocks():
        block = _load(rel)
        for ev in block.get('events', []):
            for upd in ev.get('updates', []):
                for p in upd.get('participants', []):
                    _check_ref(p.get('entity_ref', {}), rel, unreachable)
                for c in upd.get('claims', []):
                    at = c.get('attributed_to_ref')
                    if at:
                        _check_ref(at, rel, unreachable)
                    for r in (c.get('basis_refs') or []) + (c.get('supersedes_refs') or []):
                        _check_ref(r, rel, unreachable)
                for r in ((upd.get('trigger_refs') or []) + (upd.get('action_refs') or [])
                          + (upd.get('outcome_refs') or []) + (upd.get('related_event_refs') or [])):
                    _check_ref(r, rel, unreachable)
    return json.dumps({'check': 'check_ref_reachability',
                       'hit_count': len(unreachable), 'hits': unreachable}, ensure_ascii=False)


@tool
def check_orphan_claims() -> str:
    """校验 events 中 entity_ref / attributed_to_ref 指向的实体是否已建档（孤儿检测）。

    返回 JSON 字符串：{"check": "check_orphan_claims", "hit_count": N, "hits": [...]}
    """
    orphans = []
    entity_ids = set()
    chars_idx = _load('characters/index.json') or {'entries': []}
    for e in chars_idx.get('entries', []):
        rid = e.get('target', {}).get('record_id')
        if rid:
            entity_ids.add(rid)

    for rel in _iter_event_blocks():
        block = _load(rel)
        for ev in block.get('events', []):
            for upd in ev.get('updates', []):
                for p in upd.get('participants', []):
                    ref = p.get('entity_ref', {})
                    rid = ref.get('record_id')
                    if rid and rid not in entity_ids:
                        orphans.append({'record_ref': ref, 'event_id': ev.get('id'),
                                        'problem': f'参与实体 {rid} 未建档（孤儿引用）'})
                for c in upd.get('claims', []):
                    at = c.get('attributed_to_ref')
                    if at:
                        rid = at.get('record_id')
                        if rid and rid not in entity_ids:
                            orphans.append({'record_ref': at, 'claim_id': c.get('id'),
                                            'problem': f'归因实体 {rid} 未建档（孤儿引用）'})
    return json.dumps({'check': 'check_orphan_claims',
                       'hit_count': len(orphans), 'hits': orphans}, ensure_ascii=False)


@tool
def check_cutoff_leak() -> str:
    """校验 events 中 update/claim 的 revealed_at 是否超过所在 event/block 的 safe_through（时间泄漏）。

    返回 JSON 字符串：{"check": "check_cutoff_leak", "hit_count": N, "hits": [...]}
    """
    leaks = []
    for rel in _iter_event_blocks():
        block = _load(rel)
        block_st = block.get('safe_through', 0)
        for ev in block.get('events', []):
            ev_st = ev.get('safe_through', 0)
            for upd in ev.get('updates', []):
                ra = upd.get('revealed_at')
                if ra is not None and ev_st and ra > ev_st:
                    leaks.append({'record_id': upd.get('id'), 'event_id': ev.get('id'),
                                  'revealed_at': ra, 'safe_through': ev_st,
                                  'problem': 'update revealed_at > event safe_through'})
                if ra is not None and block_st and ra > block_st:
                    leaks.append({'record_id': upd.get('id'), 'event_id': ev.get('id'),
                                  'revealed_at': ra, 'safe_through': block_st,
                                  'problem': 'update revealed_at > block safe_through'})
                for c in upd.get('claims', []):
                    cra = c.get('revealed_at')
                    if cra is not None and ev_st and cra > ev_st:
                        leaks.append({'record_id': c.get('id'), 'event_id': ev.get('id'),
                                      'revealed_at': cra, 'safe_through': ev_st,
                                      'problem': 'claim revealed_at > event safe_through'})
                    if cra is not None and block_st and cra > block_st:
                        leaks.append({'record_id': c.get('id'), 'event_id': ev.get('id'),
                                      'revealed_at': cra, 'safe_through': block_st,
                                      'problem': 'claim revealed_at > block safe_through'})
    return json.dumps({'check': 'check_cutoff_leak',
                       'hit_count': len(leaks), 'hits': leaks}, ensure_ascii=False)


@tool
def check_stage_integrity() -> str:
    """校验已完整精读的 stage 是否已聚合归档（存在 commit.json）。

    返回 JSON 字符串：{"check": "check_stage_integrity", "hit_count": N, "hits": [...]}
    """
    issues = []
    sp = _load('navigation/stage-plan.json') or {'stages': []}
    max_ch = _max_committed_chapter()
    staging_stages = os.path.join(NOVEL_ROOT, '_staging', 'deepread', 'stages')
    for st in sp.get('stages', []):
        ranges = st.get('chapter_ranges', [])
        if not ranges:
            continue
        end = ranges[-1]['end']
        stage_id = st.get('id')
        if end <= max_ch:
            commit_path = os.path.join(staging_stages, f'{stage_id}.commit.json')
            if not os.path.isfile(commit_path):
                issues.append({'stage_id': stage_id, 'chapter_ranges': ranges,
                               'problem': f'stage 已完整精读（end={end} <= 已精读最大章 {max_ch}）但缺少 commit.json'})
    return json.dumps({'check': 'check_stage_integrity',
                       'hit_count': len(issues), 'hits': issues}, ensure_ascii=False)


@tool
def check_id_conflict() -> str:
    """校验 ledger 高水位与实际文件 record_id 一致（无重复、无超发）。

    返回 JSON 字符串：{"check": "check_id_conflict", "hit_count": N, "hits": [...]}
    """
    conflicts = []
    id_state = _load('ledger/id-state.json') or {'high_watermarks': {}}
    hw = id_state.get('high_watermarks', {})

    # 收集 events 中的 claim / ev / update id
    claim_ids, ev_ids, update_ids = [], [], []
    for rel in _iter_event_blocks():
        block = _load(rel)
        for ev in block.get('events', []):
            ev_ids.append(ev.get('id'))
            for upd in ev.get('updates', []):
                update_ids.append(upd.get('id'))
                for c in upd.get('claims', []):
                    claim_ids.append(c.get('id'))

    # char 实体 id
    char_ids = []
    chars_idx = _load('characters/index.json') or {'entries': []}
    for e in chars_idx.get('entries', []):
        rid = e.get('target', {}).get('record_id')
        if rid:
            char_ids.append(rid)

    for label, ids in [('char', char_ids), ('claim', claim_ids),
                       ('ev', ev_ids), ('update', update_ids)]:
        valid = [x for x in ids if x]
        # 重复检测
        dup = sorted({x for x in valid if valid.count(x) > 1})
        if dup:
            conflicts.append({'kind': label, 'problem': f'重复 record_id: {dup}'})
        # 高水位一致性
        nums = []
        for x in valid:
            m = re.match(rf'^{label}-(\d+)$', x)
            if m:
                nums.append(int(m.group(1)))
        if nums:
            mx = max(nums)
            watermark = hw.get(label, 0)
            if mx > watermark:
                conflicts.append({'kind': label,
                                  'problem': f'最大编号 {label}-{mx:04d} 超过高水位 {watermark}'})
            elif mx < watermark:
                conflicts.append({'kind': label,
                                  'problem': f'最大编号 {label}-{mx:04d} 低于高水位 {watermark}（存在空号）'})
    return json.dumps({'check': 'check_id_conflict',
                       'hit_count': len(conflicts), 'hits': conflicts}, ensure_ascii=False)


# ---------- 极简工具循环（对齐 deepread_simple.py） ----------
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


def _structured_agent_loop(system: str, user: str, tools: list, output_model, max_rounds: int = 10):
    """ReAct 循环 + 结构化提交（对齐 deepread_simple.py）。"""
    model_with_tools = model.bind_tools([*tools, output_model])
    msgs = [SystemMessage(content=system), HumanMessage(content=user)]
    tool_map = {t.name: t for t in tools}
    output_name = output_model.__name__

    for _ in range(max_rounds):
        rsp = model_with_tools.invoke(msgs)
        msgs.append(rsp)

        if not rsp.tool_calls:
            content = (rsp.content or '').strip()
            if content:
                try:
                    return output_model.model_validate(_extract_json(content))
                except Exception:
                    pass
            msgs.append(HumanMessage(content='请调用提交工具，输出最终结构化结果。'))
            continue

        for tc in rsp.tool_calls:
            name = tc['name']
            if name == output_name:
                try:
                    return output_model.model_validate(tc['args'])
                except Exception as e:
                    msgs.append(ToolMessage(
                        content=f'提交解析失败：{e}。请检查字段后重新调用提交工具。',
                        tool_call_id=tc['id'],
                    ))
                    continue
            fn = tool_map.get(name)
            out = fn.invoke(tc['args']) if fn else '未知工具'
            msgs.append(ToolMessage(content=str(out), tool_call_id=tc['id']))

    msgs.append(HumanMessage(content='信息已收集足够，请立即调用提交工具输出最终结构化结果。'))
    rsp = model.bind_tools([output_model]).invoke(msgs)
    for tc in (rsp.tool_calls or []):
        if tc['name'] == output_name:
            return output_model.model_validate(tc['args'])
    return output_model.model_validate(_extract_json(rsp.content or '{}'))


# ---------- Pydantic 结构化输出模型（对齐 04-prompt_审查.md 的 schema） ----------
class _Base(BaseModel):
    model_config = ConfigDict(extra='ignore')


class IssueUpdate(_Base):
    revealed_at: Optional[int] = None
    status: str = 'open'
    description: str = ''
    related_refs: list[dict] = Field(default_factory=list)
    source_refs: list[dict] = Field(default_factory=list)
    resolution_refs: list[dict] = Field(default_factory=list)


class RepairSuggestion(_Base):
    auto_fixable: bool = False
    action: str = 'manual'  # correct_safe_through / patch_record / manual
    detail: str = ''


class AuditIssue(_Base):
    local_id: str
    category: str = ''  # stale_source / source_locator / coverage_gap
    severity: str = 'warning'  # critical / warning
    opened_at: int = 0
    safe_through: int = 0
    updates: list[IssueUpdate] = Field(default_factory=list)
    repair_suggestion: RepairSuggestion = Field(default_factory=RepairSuggestion)


class AuditSummary(_Base):
    candidate_count: int = 0
    confirmed_issue_count: int = 0
    critical_count: int = 0
    warning_count: int = 0
    overview: str = ''


class AuditResult(_Base):
    audit_summary: AuditSummary = Field(default_factory=AuditSummary)
    issues: list[AuditIssue] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ---------- AuditAnalyzeReActAgent · System Prompt ----------
AUDIT_SYSTEM = """你是「索引质量审计员」。检查工具（F 类）已就绪：它们只读、确定性，能扫描索引产物并返回结构化的命中结果。你的任务是：自主调用这些检查工具，汇总检查结果，判定每条问题的 severity 与 category，生成 human-readable 的 issue 记录与审计汇总，反馈给用户。

## 你的工作原则

1. **你是审计员，不是重新生成员。**
   - 只判断已有索引的对错、完整性和一致性，不重新提取事实、不重写摘要
   - 通过检查工具发现问题，而不是凭空臆测
   - 发现问题时给出根因和修复建议，但不执行写入

2. **你不写文件。** 只输出结构化审计 JSON；是否修复、是否写 quality/issues/ 由分流层的确定性路径决定。

3. **主动调用检查工具（一期只调 F 类，不读原文）。**
   - 5 个检查工具：`check_ref_reachability` / `check_orphan_claims` / `check_cutoff_leak` / `check_stage_integrity` / `check_id_conflict`
   - 至少调用一次每个检查工具，确保检查覆盖完整；结果为空说明该项无问题

4. **category 与 severity 由检查类型映射（忠实遵循，不擅自改判）。**

   | 检查工具 | category | severity |
   |---|---|---|
   | check_cutoff_leak | stale_source | critical |
   | check_id_conflict | coverage_gap | critical（空号类可降为 warning） |
   | check_ref_reachability | source_locator | warning |
   | check_orphan_claims | coverage_gap | warning |
   | check_stage_integrity | coverage_gap | warning |

5. **repair_suggestion 由检查类型机械推断。**

   | 检查工具 | action | auto_fixable |
   |---|---|---|
   | check_cutoff_leak | correct_safe_through | true |
   | check_id_conflict | patch_record | true |
   | check_stage_integrity | patch_record | true |
   | check_ref_reachability | manual | false |
   | check_orphan_claims | manual | false |

6. **生成 human-readable 描述。** 把每条命中的机器可读 problem 翻译成 updates[].description，包含：发生了什么、为什么是问题、建议如何修复。描述要具体到 record_id / path 与关键数值，不泛泛而谈。

7. **汇总审计反馈。** 统计 issue 数量、critical/warning 分布，生成 audit_summary；overview 用一句话概述本批审计结论。

## 工具清单

| 工具 | 用途 |
|---|---|
| check_ref_reachability | 校验所有 Ref 的 path 可达 + record_id 可达，返回不可达清单 |
| check_orphan_claims | 校验 entity_ref/attributed_to_ref 指向的实体是否已建档，返回孤儿清单 |
| check_cutoff_leak | 校验 update/claim 的 revealed_at 是否超过 event/block 的 safe_through，返回时间泄漏清单 |
| check_stage_integrity | 校验已完整精读的 stage 是否已聚合归档（commit.json 存在），返回缺失清单 |
| check_id_conflict | 校验 ledger 高水位与实际 record_id 一致（无重复、无超发），返回冲突清单 |

## 输出格式（结构化提交）

信息收集完毕后，**必须调用提交工具**（AuditResult schema）输出最终结构化结果。字段名与类型以提交工具的 schema 为准。以下 JSON 仅为字段参考：

{
  "audit_summary": {
    "candidate_count": 5,
    "confirmed_issue_count": 3,
    "critical_count": 1,
    "warning_count": 2,
    "overview": "本批审计共发现 1 个 critical、2 个 warning。"
  },
  "issues": [
    {
      "local_id": "issue-local-1",
      "category": "source_locator",
      "severity": "warning",
      "opened_at": 0,
      "safe_through": 0,
      "updates": [
        {
          "revealed_at": null,
          "status": "open",
          "description": "events/index.json 的 entry target.path 指向 events/events-block-0001.json，但该文件不存在（实际为 events/block-0001.json），存在引用断链。",
          "related_refs": [{"path": "events/index.json", "record_id": "idx-events"}],
          "source_refs": [],
          "resolution_refs": []
        }
      ],
      "repair_suggestion": {
        "auto_fixable": false,
        "action": "manual",
        "detail": "断链引用，正确目标需人工确认，一期交人工处理。"
      }
    }
  ],
  "warnings": []
}

## 禁止事项

- ❌ 不要输出 Markdown 代码块包裹的 JSON，不要输出任何说明性文字
- ❌ 不要读原文、ledger 之外的运行材料
- ❌ 不要重新提取事实、重写摘要、修改索引内容
- ❌ 不要把正常剧情悬念记为 issue
- ❌ 不要擅自改判检查工具结果对应的 category / severity
- ❌ 不要让 severity=warning 的问题阻断发布（除非它实际是 critical）
- ❌ 不要凭空补充 source_refs（一期不读原文，source_refs 恒为空）"""

AUDIT_TOOLS = [
    check_ref_reachability,
    check_orphan_claims,
    check_cutoff_leak,
    check_stage_integrity,
    check_id_conflict,
]


# ---------- 确定性写盘（节点函数承担，Agent 不写文件） ----------
def _staging_path(rel: str) -> str:
    full = os.path.join(NOVEL_ROOT, STAGING_DIR, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    return full


def _write_audit_report(result: dict) -> None:
    path = _staging_path('report.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


# ---------- 确定性 issue 落盘（节点函数承担，Agent 不写文件） ----------
def _issue_block_index(opened_at: int) -> int:
    """按 opened_at 章节号映射到 issue 分片块号（1-based）。

    分片边界与 quality/issues.json 的 entries chapter_ranges 一致：
    1-20 → block-0001，21-40 → block-0002，41-60 → block-0003，61+ → block-0004。
    opened_at=0（一期不读原文无法定位）默认落入 block-0001。
    """
    if opened_at <= 20:
        return 1
    if opened_at <= 40:
        return 2
    if opened_at <= 60:
        return 3
    return 4


def _persist_issues(issues: list) -> dict:
    """确定性落盘：local_id → 真实 issue-*，按 opened_at 分片写入 quality/issues/block-*.json，
    更新 ledger/id-state.json 的 issue 高水位。

    issue 记录遵循 templates §8.3 schema（不含 repair_suggestion）：
    {id, category, severity, opened_at, safe_through, updates[]}

    返回 {issue_count, critical_count, warning_count, written_blocks, real_ids}。
    """
    if not issues:
        return {'issue_count': 0, 'critical_count': 0, 'warning_count': 0,
                'written_blocks': [], 'real_ids': []}

    id_state = _load('ledger/id-state.json') or {'high_watermarks': {}}
    hw = id_state.get('high_watermarks', {}).get('issue', 0)

    # local_id → 真实 issue-*，按分片分组
    blocks = {}  # block_index -> list[issue record]
    real_ids = []
    for i, iss in enumerate(issues):
        opened_at = iss.get('opened_at', 0) or 0
        real_id = f'issue-{hw + i + 1:04d}'
        real_ids.append(real_id)
        # 注意：不写 repair_suggestion，templates §8.3 的 issue 记录无此字段
        record = {
            'id': real_id,
            'category': iss.get('category', ''),
            'severity': iss.get('severity', 'warning'),
            'opened_at': opened_at,
            'safe_through': iss.get('safe_through', 0) or 0,
            'updates': iss.get('updates', []),
        }
        blocks.setdefault(_issue_block_index(opened_at), []).append(record)

    # 写分片文件
    written_blocks = []
    for block_index, records in sorted(blocks.items()):
        rel = f'quality/issues/block-{block_index:04d}.json'
        block = _load(rel)
        if block is None:
            block = {
                'schema_version': '2.0',
                'novel_id': 'wukon',
                'id': f'issues-block-{block_index:04d}',
                'kind': 'issue_collection',
                'revision': 1,
                'safe_through': 0,
                'issues': [],
            }
        block['issues'].extend(records)
        block['revision'] = block.get('revision', 1) + 1
        block['safe_through'] = max(block.get('safe_through', 0),
                                    max(r['opened_at'] for r in records))
        with open(os.path.join(NOVEL_ROOT, rel), 'w', encoding='utf-8') as f:
            json.dump(block, f, ensure_ascii=False, indent=2)
        written_blocks.append(rel)

    # 更新 issue 高水位
    id_state.setdefault('high_watermarks', {})['issue'] = hw + len(issues)
    id_state['revision'] = id_state.get('revision', 1) + 1
    with open(os.path.join(NOVEL_ROOT, 'ledger/id-state.json'), 'w', encoding='utf-8') as f:
        json.dump(id_state, f, ensure_ascii=False, indent=2)

    critical_count = sum(1 for i in issues if i.get('severity') == 'critical')
    return {'issue_count': len(issues),
            'critical_count': critical_count,
            'warning_count': len(issues) - critical_count,
            'written_blocks': written_blocks,
            'real_ids': real_ids}


# ---------- audit 节点 ----------
def audit_node(state: dict) -> dict:
    """调用 AuditAnalyzeReActAgent 执行审计，落盘报告并返回 phase。"""
    max_ch = _max_committed_chapter()

    user = f"""【任务】对 deepread 产物做质量审计：自主调用 F 类检查工具，汇总检查结果并生成审计反馈 JSON。

- novel_root: {NOVEL_ROOT}
- novel_id: wukon
- source_version: source-v1
- 审计范围: 第 1 ~ {max_ch} 章（已 committed 的剧情记录）

【可用检查工具】
check_ref_reachability / check_orphan_claims / check_cutoff_leak / check_stage_integrity / check_id_conflict

请执行：
1. 调用上述 5 个检查工具，获取结构化命中结果（每个工具至少调用一次）
2. 对每个命中结果，按 System Prompt 的映射表判定 category 与 severity，生成 human-readable 的 updates[].description 与 repair_suggestion
3. 汇总 audit_summary（candidate_count / confirmed_issue_count / critical_count / warning_count / overview）
4. 调用提交工具，以 AuditResult 的 schema 输出最终结构化结果"""

    result = _structured_agent_loop(AUDIT_SYSTEM, user, AUDIT_TOOLS, AuditResult, max_rounds=10)
    payload = result.model_dump()
    # ② 生成检查报告（落盘 _staging/audit/report.json，含 repair_suggestion 供人工参考）
    _write_audit_report(payload)

    # ③ 完成 issue 落盘（确定性：local_id → issue-*，写入 quality/issues/）
    persist = _persist_issues(payload.get('issues', []))

    summary = payload.get('audit_summary', {})
    critical_count = persist['critical_count']
    phase = 'review_issues' if critical_count > 0 else 'derive'

    print(f'\n[audit] 审计完成：{persist["issue_count"]} 个 issue'
          f'（critical {persist["critical_count"]} / warning {persist["warning_count"]}），phase -> {phase}')
    print(f'[audit] issue 已落盘：{persist["written_blocks"]}')
    print(f'[audit] 真实 issue id：{persist["real_ids"]}')
    return {'phase': phase, 'halt_reason': None,
            'issues': payload.get('issues', []),
            'audit_summary': summary,
            'persisted_issue_ids': persist['real_ids']}


# ---------- Graph ----------
class AuditState(TypedDict):
    phase: str
    halt_reason: str
    issues: list
    audit_summary: dict
    persisted_issue_ids: list


def build_graph():
    graph = StateGraph(AuditState)
    graph.add_node('audit', audit_node)
    graph.add_edge(START, 'audit')
    graph.add_edge('audit', END)
    return graph.compile()


if __name__ == '__main__':
    app = build_graph()
    final = app.invoke({'phase': 'audit', 'halt_reason': None, 'issues': [], 'audit_summary': {}})
    print('\n================ audit 结果 ================')
    print(f"phase: {final.get('phase')}")
    print(f"halt_reason: {final.get('halt_reason')}")
    summary = final.get('audit_summary', {})
    print(f"issue 总数: {summary.get('confirmed_issue_count', 0)}"
          f"（critical {summary.get('critical_count', 0)} / warning {summary.get('warning_count', 0)}）")
    print(f"检查报告: {os.path.join(NOVEL_ROOT, STAGING_DIR, 'report.json')}")
    print(f"issue 落盘: {final.get('persisted_issue_ids')}")
    for iss in final.get('issues', []):
        print(f"  - [{iss.get('severity')}] ({iss.get('category')}) {iss.get('local_id')}")
