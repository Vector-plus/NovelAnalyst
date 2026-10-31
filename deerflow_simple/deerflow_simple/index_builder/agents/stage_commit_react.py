"""StageCommitReActAgent —— deepread 阶段聚合 Agent 装配。

对应设计文档《04-prompt_第二阶段精读.md》§2。

- stage 尾章触发，单次 LLM（输入 buffer 已缓存，失败重试 ≤2 次）。
- 工具：B 类（fetch_entity_current）+ E 类（fetch_entity_summary /
  fetch_event_detail / fetch_related_claims / list_entity_stages）。
- 输出：``StageCommitPayload`` JSON，由节点函数解析后调写入服务落盘。

装配与 ChapterReActAgent 同惯例：create_agent 原语 + Pydantic 兜底校验
（schemas.StageCommitPayload），System Prompt 模块级常量（R1），动态变量只进 User 段。
"""

from __future__ import annotations

from langchain.agents import create_agent

from deerflow_simple.config import SimpleConfig
from deerflow_simple.index_builder.tools.entity import build_entity_tools
from deerflow_simple.index_builder.tools.stage_query import build_stage_query_tools
from deerflow_simple.model import create_chat_model

# 模块级 System Prompt（来自 04-prompt_第二阶段精读.md §2.2，禁止 f-string）
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

## 输出格式（严格 JSON）

你的最终答复必须是单一 JSON 对象，不要包 markdown 代码块。schema 如下：

```json
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
      "subject_refs": [
        {"path": "characters/char-0001/index.json", "record_id": "char-0001"}
      ],
      "record_refs": [
        {"path": "events/block-0003.json", "record_id": "ev-0025"}
      ],
      "source_refs": []
    },
    "body_markdown": "## 阶段范围\\n第85—128章，外门试炼开始到结束。[[ev-0025]]\\n\\n## 起始局面\\n林舟入宗后被分到最差执事处。\\n\\n## 核心目标与冲突\\n通过外门考核进入内门。\\n\\n## 关键转折\\n考核中段爆发资源争斗事件。\\n\\n## 阶段结果\\n林舟以第七名通过考核，进入内门。\\n\\n## 下一阶段承接与未决问题\\n内门弟子身份带来的新宗门任务未展开。"
  },
  "character_stages": [
    {
      "entity_ref": {"path": "characters/char-0001/index.json", "record_id": "char-0001"},
      "stage_doc_id": "doc-char-0001-stage-003",
      "stage_markdown": {
        "front_matter": {
          "title": "外门试炼阶段",
          "chapter_ranges": [{"start": 85, "end": 128}],
          "as_of": 128,
          "subject_refs": [{"path": "characters/char-0001/index.json", "record_id": "char-0001"}],
          "record_refs": [
            {"path": "events/block-0003.json", "record_id": "ev-0025"}
          ],
          "source_refs": []
        },
        "body_markdown": "## 阶段起点\\n...\\n\\n## 目标与动机\\n...\\n\\n## 关键选择与经历\\n...[[ev-0025]]\\n\\n## 阶段终点\\n..."
      },
      "current_summary_update": "历经外门试炼，以第七名通过考核进入内门。",
      "identity_notes_appends": []
    }
  ],
  "faction_stages": [],
  "faction_landscape": {"produce": false, "reason": "本阶段势力格局无实质变化"},
  "relationship_snapshots": [],
  "emotional_stages": [],
  "thread_updates": [],
  "warnings": [],
  "notes_for_audit": []
}
```

### 字段说明

- `arc_summary.doc_id`、`character_stages[].stage_doc_id` 等由节点函数通过 ID 分配器或固定命名得到；此处可留 local_id 等待填充
- `relationship_ref_or_new` 支持：
  - 已有：`{"existing_ref": {...}}`
  - 新建：`{"new_rel": {"subjects": [...], "introduced_at": N}}`
- `emotional_ref_or_new` 同上
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
- ❌ 不要修改 stage-plan 骨架（骨架已 confirmed，不可变）
"""


def build_stage_commit_react_agent(config: SimpleConfig, novel_root: str):
    """装配 StageCommitReActAgent（无状态，按 novel_root 复用）。"""
    model = create_chat_model(config, temperature=0.2, max_tokens=config.index_max_tokens)
    # B 类取 fetch_entity_current；其余为 E 类查询工具。
    fetch_current = [
        t for t in build_entity_tools(novel_root) if t.name == "fetch_entity_current"
    ]
    tools = [*fetch_current, *build_stage_query_tools(novel_root)]
    return create_agent(
        model=model,
        tools=tools,
        system_prompt=STAGE_COMMIT_SYSTEM,
    )


def build_stage_commit_react_prompt(
    novel_root: str,
    novel_id: str,
    source_version: str,
    total_chapters: int,
    stage_id: str,
    stage_title: str,
    stage_start: int,
    stage_end: int,
    stage_buffer_json: str = "",
    involved_characters: str = "",
    involved_factions: str = "",
    involved_relationships: str = "",
    involved_emotions: str = "",
    involved_threads: str = "",
    entity_current_digest: str = "",
) -> str:
    """构造 StageCommitReActAgent 的 User Prompt（来自 04-prompt §2.3 模板）。"""
    return (
        f"【任务】对以下 stage 做阶段聚合，产出 stage 级 Markdown 与关系/感情快照。\n\n"
        f"- novel_root: {novel_root}\n"
        f"- novel_meta: {{\"novel_id\": \"{novel_id}\", \"source_version\": \"{source_version}\", "
        f"\"total_chapters\": {total_chapters}}}\n"
        f"- stage_ref: {{\"path\": \"navigation/stage-plan.json\", \"record_id\": \"{stage_id}\"}}\n"
        f"- stage_title: {stage_title}\n"
        f"- stage_range: {stage_start} ~ {stage_end}\n"
        f"- as_of: {stage_end}\n\n"
        f"【stage_buffer（本阶段章节已提取的事件/陈述/转折点聚合）】\n"
        f"{stage_buffer_json or '（暂无）'}\n\n"
        f"【本阶段涉及实体清单】\n"
        f"- 人物候选/确认实体: {involved_characters or '（无）'}\n"
        f"- 势力候选/确认实体: {involved_factions or '（无）'}\n"
        f"- 已有关系对: {involved_relationships or '（无）'}\n"
        f"- 已有感情线: {involved_emotions or '（无）'}\n"
        f"- 已有故事线: {involved_threads or '（无）'}\n\n"
        f"【本阶段已有实体档案摘要（current_summary 节选）】\n"
        f"{entity_current_digest or '（暂无）'}\n\n"
        f"请执行：\n"
        f"1. 从 stage_buffer 中识别哪些实体在本阶段**确有实质经历**（出现在 ≥2 个关键事件 / 有身份变化 / 有重要选择）\n"
        f"2. 对确有经历的实体：调 `list_entity_stages` 查已有 stage 编号；必要时调 `fetch_entity_current` 读 current_summary；产出 character_stage / faction_stage Markdown\n"
        f"3. 对本阶段涉及的关系对：必要时调 `fetch_event_detail` 读关键事件；产出关系阶段快照\n"
        f"4. 对本阶段情感互动：判断是否够升为 assessment（谨慎用 romantic）；产出 emotional_stage Markdown + assessment\n"
        f"5. 产出 arc_summary（本 stage 剧情总览）\n"
        f"6. 更新相关 story_thread\n"
        f"7. 输出符合 schema 的 StageCommitPayload JSON（单一 JSON 对象，无 markdown 包裹）"
    )
