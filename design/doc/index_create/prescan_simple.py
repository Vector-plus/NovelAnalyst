import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import TypedDict

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.constants import START, END
from langgraph.graph import StateGraph

load_dotenv()

# ---------- 配置 ----------
NOVEL_ROOT = os.getenv(
    'PRESCAN_NOVEL_ROOT',
    '/Users/wickfu/code/cls-ai/deer-flow/xianni_test/work_test/novel',
)
# 默认只扫前 2 卷做验证（可用环境变量覆盖）
MAX_VOLS = int(os.getenv('PRESCAN_MAX_VOLS', '3'))
# 并发扫描的卷数（fan-out 线程数）
PRESCAN_CONCURRENCY = int(os.getenv('PRESCAN_CONCURRENCY', '3'))

model = init_chat_model(
    model_provider=os.getenv('DEEPSEEK_PROVIDER', 'openai'),
    model=os.getenv('DEEPSEEK_MODEL', 'deepseek-chat'),
    base_url=os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com/v1'),
    temperature=0.2,
    api_key=os.getenv('DEEPSEEK_API_KEY'),
)
# model = init_chat_model(
#     model_provider=os.getenv('OPENROUTER_PROVIDER', 'openai'),
#     model=os.getenv('OPENROUTER_MODEL', 'minimax/minimax-m3.1-flash:free'),
#     base_url=os.getenv('OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1'),
#     temperature=0.2,
#     api_key=os.getenv('OPENROUTER_API_KEY'),
# )


# ---------- 文件读取辅助 ----------
def _load(rel_path: str) -> dict:
    with open(os.path.join(NOVEL_ROOT, rel_path), encoding='utf-8') as f:
        return json.load(f)


# ---------- 通用文件系统工具（LLM 自主导航，工具不做路径推导和 JSON 解析） ----------
@tool
def list_dir(rel_path: str = '') -> str:
    """列出小说根目录下指定子目录的内容。

    参数:
        rel_path: 相对小说根目录的路径，'' 表示根目录。

    返回:
        JSON 字符串：{"path": 路径, "entries": [{"name": 名称, "type": "dir"/"file", "size": 字节}]}
    """
    root = os.path.realpath(NOVEL_ROOT)
    target = os.path.realpath(os.path.join(NOVEL_ROOT, rel_path))
    if not target.startswith(root + os.sep) and target != root:
        return '非法路径：越出小说根目录'
    if not os.path.isdir(target):
        return f'不是目录: {rel_path}'

    entries = []
    for name in sorted(os.listdir(target)):
        p = os.path.join(target, name)
        if os.path.isdir(p):
            entries.append({'name': name, 'type': 'dir'})
        else:
            entries.append({'name': name, 'type': 'file', 'size': os.path.getsize(p)})
    return json.dumps({'path': rel_path or '/', 'entries': entries}, ensure_ascii=False)


@tool
def read_file(rel_path: str, offset: int = 0, limit: int = 20000) -> str:
    """读取小说根目录下任意文件的原始内容，不做任何解析。

    参数:
        rel_path: 相对小说根目录的文件路径，如 'source/index.json' 或 'source/vol-001/ch-000001.txt'。
        offset: 起始字符偏移（默认 0）。
        limit: 最多返回字符数（默认 20000，大文件保护）。

    返回:
        文件原始文本，前面附带一行元信息（文件总字符数、本次返回范围、是否截断）。
    """
    root = os.path.realpath(NOVEL_ROOT)
    target = os.path.realpath(os.path.join(NOVEL_ROOT, rel_path))
    if not target.startswith(root + os.sep) and target != root:
        return '非法路径：越出小说根目录'
    if not os.path.isfile(target):
        return f'文件不存在: {rel_path}'

    with open(target, encoding='utf-8') as f:
        content = f.read()
    total = len(content)
    seg = content[offset:offset + limit]
    truncated = offset + limit < total
    header = f'[文件 {rel_path} | 总字符 {total} | 返回 {offset}~{offset + len(seg)}]'
    if truncated:
        header += '（已截断，继续读请调大 offset）'
    return f'{header}\n{seg}'


# 记录 write_file 的写入结果，供 merge_vols 取回（merge 为单次调用，无并发）
_written: dict = {}


@tool
def write_file(rel_path: str, content: str) -> str:
    """将内容写入小说根目录下指定路径的文件（自动创建父目录）。

    参数:
        rel_path: 相对小说根目录的文件路径，如 'navigation/stage-plan.json'。
        content: 要写入的完整文本内容（JSON 请序列化为字符串）。

    返回:
        写入成功/失败的提示信息。
    """
    root = os.path.realpath(NOVEL_ROOT)
    target = os.path.realpath(os.path.join(NOVEL_ROOT, rel_path))
    if not target.startswith(root + os.sep) and target != root:
        return '非法路径：越出小说根目录'

    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, 'w', encoding='utf-8') as f:
        f.write(content)
    _written[rel_path] = content
    return f'已写入 {rel_path}（{len(content)} 字符）'


# ---------- 极简工具循环（对齐 simple-agent.py 的 bind_tools 用法） ----------
def _agent_loop(system: str, user: str, tools: list, max_rounds: int = 8, require_json: bool = False) -> str:
    """让模型在多轮里自主调用工具，直到输出最终文本。

    require_json=True 时，会对最终文本做 JSON 合法性校验，非法则要求模型修复重试。
    """
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
    # 循环耗尽仍未收敛：强制模型停止调工具，直接输出最终 JSON（同样做校验重试）
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
                content='输出仍不是合法 JSON，请修复语法错误（如分号误用为逗号、缺少逗号、引号未闭合）后重新输出完整 JSON。'
            ))
    return content


def _extract_json(text: str) -> dict:
    text = (text or '').strip()
    # 去掉可能的 BOM
    if text.startswith('\ufeff'):
        text = text[1:].strip()
    if text.startswith('```'):
        text = text.strip('`')
        if text.startswith('json'):
            text = text[4:]
    s = text.find('{')
    e = text.rfind('}')
    if s == -1 or e == -1:
        preview = text[:200] if text else '(空文本)'
        raise ValueError(f'未找到 JSON：{preview}')
    raw = text[s:e + 1]

    # 依次尝试多种修复策略（LLM 生成 JSON 的常见错误），任一成功即返回
    candidates = [raw]
    # ① 尾逗号修复：{"a": 1,} → {"a": 1}
    candidates.append(re.sub(r',\s*([}\]])', r'\1', raw))
    # ② 分号误作数组/对象分隔符：{...};{...} 或 [...];[...] → 逗号
    candidates.append(re.sub(r'([}\]])\s*;\s*(?=[{\[])', r'\1, ', raw))
    # ③ 尾逗号 + 分号 组合
    t = re.sub(r',\s*([}\]])', r'\1', raw)
    candidates.append(re.sub(r'([}\]])\s*;\s*(?=[{\[])', r'\1, ', t))

    last_err = None
    for c in candidates:
        try:
            return json.loads(c)
        except json.JSONDecodeError as err:
            last_err = err

    # 全部失败，定位出错位置附近的内容，便于排查
    pos = last_err.pos
    ctx = raw[max(0, pos - 80):pos + 80]
    raise ValueError(
        f'JSON 解析失败（第 {last_err.lineno} 行第 {last_err.colno} 列）：{last_err.msg}\n'
        f'出错位置附近：...{ctx}...'
    )


# ---------- ① ScanVol：扫读单卷 ----------
SCAN_SYSTEM = """你是「单卷扫读分析员」。你负责在不加载全书的前提下，快速扫读一卷（通常 20–50 章）原文，产出一份**结构化卷报告 VolReport**，供下游「阶段计划合并员」拼成全书阶段骨架。

## 你的工作原则

1. **你是扫读员，不是精读员。**
   - 不做事实核验、不做人物画像、不做关系推断。
   - 不对任何原文结论下定论；一切输出都是「候选」。
   - 你发现的转折和冲突仅用来说明阶段边界，不作为事实落库。

2. **阶段切分优先依据（按顺序）**
   - ① 主角主要目标发生变化（例如：从「拜师学艺」切换到「宗门任务」）
   - ② 核心冲突收束或新冲突主导（例如：主线反派更替、长期矛盾解决）
   - ③ 长期场景转换（例如：下山、入宗、历练远行，持续影响后续多章）

   **以下情况不作为阶段边界**：
   - 单次战斗、普通对话、短暂换场景
   - 一两章的插曲、过场剧情
   - 情绪波动、单一事件内的小高潮

3. **以卷界为候选，不强求对齐**
   - 本卷**可能**构成一个阶段，也可能内部拆成多个阶段，也可能只是某跨卷阶段的一部分
   - 你只需要**诚实报告**在本卷范围内观察到的阶段边界候选，让下游决定如何合并

4. **人物候选只记名字，不做实体消解**
   - 只记录在本卷中有持续经历或多次出场的角色名字
   - 不要尝试合并化名/绰号/身份，这是精读阶段的工作
   - 一次性路人、单章配角可以忽略

## 目录结构与文件导航

小说根目录（novel_root）下的关键结构：

- `manifest.json`：小说元信息（novel_id、title、author、source_version）
- `source/index.json`：全书卷清单。`entries` 数组，每项含 `chapter_ranges`（该卷章节范围）和 `target.path`（指向 `source/vol-XXX/index.json`）
- `source/vol-XXX/index.json`：单卷章节清单。`chapters` 数组，每项含 `chapter_order`（章节号）、`title`（章名）、`path`（章节原文相对路径，如 `source/vol-001/ch-000001.txt`）
- `source/vol-XXX/ch-NNNNNN.txt`：章节原文正文

**导航方法**（工具只做「列目录」和「读原始文本」，不帮你解析，请自行解读）：
1. 用 `list_dir` 查看目录内容（如 `list_dir('')`、`list_dir('source/vol-001')`）
2. 用 `read_file` 读取 index.json（会返回 JSON 原文，请自行解析出章节号、章名、章节文件路径）
3. 根据 index.json 中 `chapters[].path` 定位章节原文，再用 `read_file` 读取正文

## 工具使用策略

- `list_dir(rel_path)`：列出目录内容
- `read_file(rel_path)`：读任意文件原始内容（JSON 返回原文自行解析；txt 返回正文）

**建议扫读节奏**：
- 先读 `source/{vol_id}/index.json` 获得该卷章节清单
- 卷首 1–2 章完整读，建立主基调
- 中间章节采样读（每 3–5 章完整读 1 章，关键转折章节完整读）
- 卷尾 1–2 章完整读，捕捉阶段收束
- 发现疑似边界章节时**完整读**该章

## 输出格式（严格 JSON）

你的最终答复必须是一个符合下列 schema 的 JSON，不要包含任何额外文字：

```json
{
  "vol_id": "vol-003",
  "chapter_range": {"start": 85, "end": 128},
  "scanned_chapters": [85, 86, 90, 95, 100, 105, 110, 115, 120, 125, 128],
  "stage_candidates": [
    {
      "local_id": "cand-1",
      "chapter_ranges": [{"start": 85, "end": 112}],
      "title_hint": "入宗试炼",
      "primary_goal": "通过宗门外门考核",
      "core_conflict": "外门弟子内卷与资源争夺",
      "key_turning_points": [
        {"chapter": 95, "note": "主角被安排到最差执事处"},
        {"chapter": 108, "note": "试炼总排名公布"}
      ],
      "boundary_reason": "本段以外门考核目标统领，第 112 章考核结束后主线切向内门，故在此断"
    }
  ],
  "character_mentions": [
    {"name": "林舟", "first_chapter": 85, "last_chapter": 128, "role_hint": "主角"},
    {"name": "沈岚", "first_chapter": 87, "last_chapter": 125, "role_hint": "同门"}
  ],
  "cross_volume_hint": {
    "head_continues_from": "疑似承接上卷「拜师」阶段，前几章仍在交代上一阶段余波",
    "tail_opens_to": "尾章出现神秘玉简，疑似开启下一阶段主线"
  },
  "warnings": [
    "第 100–105 章跳过未读，若合并时发现边界存疑请回查"
  ]
}
```

## 禁止事项

- ❌ 不要输出 Markdown、不要输出解释性文字、不要输出 ```json 代码块包裹（除非 schema 要求）
- ❌ 不要把普通战斗/对话/过场列为 stage_candidate
- ❌ 不要对人物身份/化名做任何合并判断
- ❌ 不要预测未扫章节的内容
- ❌ `scanned_chapters` 必须是**真实调用过 read_file 读取正文的章节号**，不能虚报"""


def scan_vol(vol_id: str, start: int, end: int, vol_index: int, total_vols: int) -> dict:
    user = f"""【任务】扫读以下单卷并产出 VolReport。

- novel_root: {NOVEL_ROOT}
- vol_id: {vol_id}
- chapter_range: {start} ~ {end}（共 {end - start + 1} 章）
- current_vol_index: {vol_index} / {total_vols}

请自主导航：
1. 用 list_dir 查看根目录与 source 目录结构
2. 用 read_file 读取 source/{vol_id}/index.json 获得该卷章节清单（JSON 原文，自行解析）
3. 按扫读节奏用 read_file 读取章节正文（source/{vol_id}/ch-NNNNNN.txt）
4. 产出符合 schema 的 VolReport JSON（单一 JSON 对象，无 markdown）"""

    text = _agent_loop(SCAN_SYSTEM, user, [list_dir, read_file], max_rounds=15, require_json=True)
    return _extract_json(text)


# ---------- ② Merge：合并所有卷报告 ----------
MERGE_SYSTEM = """你是「阶段计划合并员」。你拿到的是全书所有卷的扫读报告 List[VolReport]，需要合并成一份**全书阶段骨架 stage-plan.draft.json**，供人工审核后冻结进入精读阶段。

## 你的工作原则

1. **你是合并员，不是重新扫读员。**
   - 输入已经包含每卷的 stage_candidates、人物提及、跨卷衔接提示
   - 你的主要工作是**跨卷对齐、合并同类项、消解边界歧义、校验连续性**
   - 只在必须判断「某卷卷首 vs 上卷卷尾应否合并为同一阶段」时才用 read_file 回查原文

2. **阶段切分最终准则**（与 ScanVol 一致）
   - ① 主要目标变化    ② 核心冲突收束    ③ 长期场景转换
   - 普通战斗/对话/短暂换场景不独立成阶段

3. **跨卷合并策略**
   - 若 A 卷的尾部 stage_candidate 与 B 卷的头部 stage_candidate 在**目标和冲突**上延续，合并为一个跨卷阶段
   - 若 A 卷整卷只对应一个候选，B 卷头部 cross_volume_hint.head_continues_from 显示延续，合并
   - 若多个卷的候选都很零碎（例如每卷 3–5 个候选），要**向上合并**到更粗粒度，避免阶段过碎
   - 全书建议阶段数量通常在 **5–15 个**之间；超过 20 个请再检查是否过度拆分

4. **character_candidates 合并规则**
   - 跨卷同名合并为同一候选，chapter_ranges 合并为**连续或非连续区间**
   - **不**跨名合并（即便疑似化名/绰号），精读阶段才消解
   - 一次性/路人角色（仅在一卷出现 ≤2 章）过滤掉
   - 建议最终 character_candidates 控制在 **30–100 个**之间

5. **硬校验（必须全部通过才输出）**
   - 所有 stages 的 chapter_ranges **连续、无重叠、无遗漏**
   - 第一个 stage 从章节 1 开始，最后一个 stage 到 total_chapters 结束
   - `scanned_ranges` = 各 VolReport 的 `scanned_chapters` 并集（去重，升序）
   - 每个 stage 必填 `boundary_reason`
   - `status` = `"draft"`
   - `revision` = 1
   - `safe_through` = 1（草案阶段固定，待人工 confirmed 后再推进）

## 目录结构与工具

小说根目录（novel_root）下关键结构：
- `manifest.json`：小说元信息（novel_id、title、author、source_version）
- `source/index.json`：全书卷清单（entries[].chapter_ranges + target.path）
- `source/vol-XXX/index.json`：单卷章节清单（chapters[].chapter_order、title、path）
- `source/vol-XXX/ch-NNNNNN.txt`：章节原文
- `navigation/stage-plan.json`：合并产出的最终落盘位置

可用工具：
- `list_dir(rel_path)`：列出目录内容
- `read_file(rel_path)`：读任意文件原始内容（JSON 返回原文自行解析；txt 返回正文）
- `write_file(rel_path, content)`：将内容写入指定路径（自动创建父目录）

**工具调用约定**：
1. 合并完成后，**必须**调用 `write_file` 把最终 stage-plan JSON 写入 `navigation/stage-plan.json`（字符串内容）
2. `read_file` 仅用于跨卷衔接存疑时回查原文，总调用 ≤ 3 次，默认不调用

## 输出格式（严格 JSON，对齐 templates §11.1）

你的最终答复必须是单一 JSON 对象，不要包含 markdown 代码块、不要包含任何解释性文字。

```json
{
  "schema_version": "2.0",
  "novel_id": "zhuxian",
  "id": "stage-plan",
  "kind": "stage_plan",
  "revision": 1,
  "safe_through": 1,
  "source_version": "source-v1",
  "status": "draft",
  "scanned_ranges": [{"start": 1, "end": 124}],
  "stages": [
    {
      "id": "stage-001",
      "title": "初识与入门",
      "volume_ids": ["vol-001"],
      "chapter_ranges": [{"start": 1, "end": 44}],
      "boundary_reason": "..."
    }
  ],
  "character_candidates": [
    {"name": "张小凡", "chapter_ranges": [{"start": 1, "end": 124}]}
  ],
  "merge_notes": [
    "vol-002 尾 + vol-003 头合并为 stage-002（目标连续：外门修炼）",
    "过滤 X 个一次性配角"
  ]
}
```

## 禁止事项

- ❌ 不要输出 Markdown 或任何说明性文字，只输出 JSON
- ❌ 不要修改任何 VolReport 的事实（如改章节号、改人物名）
- ❌ 不要自作主张合并化名、绰号或疑似同一人物
- ❌ 不要让 chapter_ranges 出现跳章、重叠、超过 total_chapters
- ❌ 不要把 status 置为 `"confirmed"`
- ❌ 不要预测或虚构 VolReport 中未提及的人物或情节"""


def merge_vols(vol_reports: list[dict]) -> dict:
    manifest = _load('manifest.json')
    si = _load('source/index.json')
    novel_id = manifest.get('novel_id', 'unknown')
    source_version = manifest.get('source_version', 'source-v1')
    total_chapters = si['scope']['chapter_ranges'][0]['end']
    total_vols = len(si['entries'])

    user = f"""【任务】合并以下所有卷扫读报告，产出全书 stage-plan.draft.json。

- novel_root: {NOVEL_ROOT}
- novel_meta:
  - novel_id: {novel_id}
  - title: {manifest.get('title', '')}
  - author: {manifest.get('author', '')}
  - source_version: {source_version}
  - total_chapters: {total_chapters}
  - total_vols: {total_vols}

【输入 VolReports】（按卷序排列）
{json.dumps(vol_reports, ensure_ascii=False, indent=2)}

请执行：
1. 跨卷合并同类 stage_candidate
2. 合并 character_candidates，过滤路人
3. 执行所有硬校验（连续性、无重叠、无遗漏）
4. 用 write_file 工具把最终 stage-plan JSON 写入 navigation/stage-plan.json"""

    _written.clear()
    text = _agent_loop(MERGE_SYSTEM, user, [list_dir, read_file, write_file], max_rounds=15)

    # 优先取 LLM 通过 write_file 写入的结果：遍历所有写入，容忍路径偏差与 markdown 包裹
    plan = None
    for path, content in _written.items():
        try:
            candidate = json.loads(content)
        except Exception:
            try:
                candidate = _extract_json(content)
            except Exception:
                continue
        if isinstance(candidate, dict) and 'stages' in candidate:
            plan = candidate
            print(f'[write] 完整 stage-plan 已由 merge_agent 写入 {path}')
            break

    # 兜底：解析文本输出
    if plan is None:
        plan = _extract_json(text)
        print('[warn] merge_agent 未通过 write_file 产出合法结果，回退解析文本输出')

    return plan


# ---------- Graph ----------
class PrescanState(TypedDict):
    vols: list          # 待扫描的卷清单 [{vol_id, start, end}]，由外层 agent 注入
    vol_reports: list
    stage_plan: dict


def list_volumes() -> list:
    """从 source/index.json 枚举全部卷清单。

    缺省用；外层 agent 也可自行决定扫哪些卷后，直接注入 state['vols']。
    """
    si = _load('source/index.json')
    vols = []
    for entry in si['entries']:
        vol_id = entry['target']['path'].split('/')[1]
        r = entry['chapter_ranges'][0]
        vols.append({'vol_id': vol_id, 'start': r['start'], 'end': r['end']})
    return vols


def prescan_node(state: PrescanState) -> dict:
    # 卷清单优先取 state（外层 agent 可控制扫哪些卷）；缺省则枚举全部并按 MAX_VOLS 截断
    vols = state.get('vols') or list_volumes()
    if not state.get('vols'):
        vols = vols[:MAX_VOLS]

    total_vols = len(vols)

    def _scan_one(args):
        v, i = args
        print(f'[scan] {v["vol_id"]} (第{v["start"]}-{v["end"]}章) ...')
        return scan_vol(v['vol_id'], v['start'], v['end'], i + 1, total_vols)

    # fan-out：并发扫描各卷（03 §2.2：Python 控制并发，非串行）
    tasks = [(v, i) for i, v in enumerate(vols)]
    with ThreadPoolExecutor(max_workers=PRESCAN_CONCURRENCY) as ex:
        reports = list(ex.map(_scan_one, tasks))

    # fan-in：单次合并（merge_vols 内部完成 stage-plan.json 写盘）
    plan = merge_vols(reports)

    return {'vol_reports': reports, 'stage_plan': plan}


def build_graph():
    graph = StateGraph(PrescanState)
    graph.add_node('prescan', prescan_node)
    graph.add_edge(START, 'prescan')
    graph.add_edge('prescan', END)
    return graph.compile()


if __name__ == '__main__':
    app = build_graph()
    # 外层 agent 通过 PrescanState.vols 注入要扫描的卷；此处演示默认扫前 MAX_VOLS 卷
    vols = list_volumes()[:MAX_VOLS]
    final = app.invoke({'vols': vols})

    plan = final.get('stage_plan', {})
    print('\n================ 阶段清单 ================')
    for st in plan.get('stages', []):
        ranges = ', '.join(f"{r['start']}-{r['end']}" for r in st['chapter_ranges'])
        print(f"  [{st['id']}] {st['title']}  (ch {ranges})")
        print(f"      理由: {st['boundary_reason']}")
    print(f'\n候选人物: {len(plan.get("character_candidates", []))} 个')
    print(f'merge_notes: {plan.get("merge_notes", [])}')
