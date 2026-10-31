---
name: novel-narration-generator
description: Use this skill when the user asks to produce narrated commentary ("解说词"/"解说稿") for a long-form novel that has already been indexed per the novel-index-templates.md v2.0 spec. Supports five themes - chapter plot explanation (章节剧情解说), character biography (人物传记), faction landscape (势力格局), worldbuilding/powersystem (体系设定), and emotional arc analysis (感情线解析). Trigger on requests like "生成章节解说"、"写一篇人物传记解说"、"讲一下这几章的剧情"、"分析一下 XX 势力格局"、"讲清楚这个修炼体系"、"解析 XX 和 YY 的感情线"、"小说解说词". The skill is a read-only consumer of an existing novel/ index tree and never writes back to it.
version: 1.0.0
allowed-tools:
  - read_file
  - ls
  - load_manifest
  - load_task_routes
  - load_entity
  - load_chapter_ledger
  - search_name
  - ask_clarification
  - report_gap
---

# Novel Narration Generator Skill

## 概览

本 Skill 面向**已按 `novel-index-templates.md` v2.0 规范建立结构化索引**的长篇小说（约 600 万字量级）。它作为**纯只读消费端**，按主题路由加载索引材料，再经原文回读核验后，产出**前因后果清晰、逻辑严谨、文风鲜明、看了一集还想追下一集**的解说稿。

Skill 覆盖以下五类解说（下文统称"五类解说"）：

| task_type | 中文名 | 字数区间        | 文风 |
|---|---|-------------|---|
| `chapter_explanation` | 章节剧情解说 | 1500–2500 字 | 章回体 + 悬念牵引 |
| `biography` | 人物传记解说 | 3000-4000 字 | 人物弧光 + 命运叙事 |
| `faction_landscape` | 势力格局解说 | 1000–1500 字 | 棋局推演 + 利益分析 |
| `worldbuilding` | 体系设定解说 | 1000–1500 字 | 纪录片 + 爽文解构 |
| `emotional_arc` | 感情线解析 | 1000–1500 字 | 心流叙事 + 情感考古 |

> **Skill 的只读契约**：本 Skill **不写入**任何索引文件、**不触发**账本/编号/覆盖的变更。全部产出以稿件形式返回给调用方。

---

## 主流程（6 步）

当收到解说任务时，LLM 必须严格按以下 6 步执行，**禁止跳过**：

1. **解析输入**：按 §输入契约 校验参数；缺失必填字段 / 收到不兼容参数（如 `mode=cutoff`）**立刻报错**，不要静默降级。
2. **查检索指南**：加载 `references/retrieval-playbook.md`，根据 `task_type` 定位该主题的"入口 → 必读 → 可选 → 停止条件"路径。
3. **加载材料**：从 `novel/manifest.json` 开始，依次读取 `navigation/catalog.json` → `navigation/task-routes.json` → `navigation/names/*` → 各主题索引文件；累计加载量接近 `task_token_budget`（默认 32000 tokens）的 90% 时停止扩展，不得悄悄截断。
4. **原文核验**：对关键结论型 Claim（身份揭示、重大反转、关系定性、能力规则等）使用 `SourceRef.anchor` 回读 `source/vol-*/ch-*.txt`；anchor 缺失则扩读整章并在稿件尾部标注"证据有限"。
5. **按主题文风撰写**：加载 `references/style-guide-*.md` 与 `references/structure-templates.md`，按对应文风与结构模板起草稿件。证据与推断必须按 `references/evidence-and-boundary.md` 的规则**严格分离**。
6. **自检并输出**：按 §自检清单 逐项核对；全部通过方可输出。输出格式见 §输出结构。

---

## 输入契约

Skill 支持以下输入字段（对应 `RetrievalTask` 的子集）：

| 字段 | 类型 | 必填规则 | 说明                                                                                                |
|---|---|---|---------------------------------------------------------------------------------------------------|
| `novel_root` | string | **必填** | 指向索引根 `xianni_test/novel/` 的绝对或相对路径                                                               |
| `task_type` | enum | **必填** | 五选一：`chapter_explanation` / `biography` / `faction_landscape` / `worldbuilding` / `emotional_arc` |
| `subject` | string \| Ref | **见下表** | 目标主体（人物名、势力名、设定名或 Ref）                                                                            |
| `focus_ranges` | `ChapterRange[]` | **见下表** | 章节范围，如 `[{"from":"ch-0001","to":"ch-0020"}]`                                                      |
| `extra_hint` | string | 可选 | 用户补充的侧重点（例如"重点讲他叛变前后的心路变化"）                                                                       |
| `output_language` | string | 可选 | 输出语言，默认 `zh-CN`                                                                                   |

**各 task_type 的必填矩阵：**

| task_type | `subject` | `focus_ranges` |
|---|---|---|
| `chapter_explanation` | 可选（可用 focus_ranges 内主要出场人物自动展开） | **必填** |
| `biography` | **必填** | 可选（不填则覆盖人物全部已索引阶段） |
| `faction_landscape` | 可选（不填 → 讲一期格局总览；填则聚焦该势力） | 可选 |
| `worldbuilding` | **必填**（具体设定名或 `setting-*` Ref） | 可选 |
| `emotional_arc` | **必填**（人物对或 `emo-*` Ref） | 可选 |

**歧义处理：**

- `subject` 以**名称字符串**传入时，必须先经 `navigation/names/index.json` → `navigation/names/part-*.json` 做精确匹配。
- 命中 ≥ 2 个候选时，**不得擅自选择**，必须向调用方返回"歧义待消解"并列出候选 `entity_ref` 与简述。
- `focus_ranges` 中若有章节 > `manifest.published_through`，以 `published_through` 为上限并在元信息中告知"后续章节尚未发布索引"。

---

## 一期视角约束

一期（v1.0.0）固定 `mode=full`，不启用严格 `cutoff` 投影（遵循索引模板 §10）：

- 索引中的 `revealed_at`、`safe_through` 等字段**仅用于叙述顺序控制**（后文揭示的真相不能当作主角当时的已知）。
- **收到 `mode=cutoff` 或任何"严格防剧透"参数时，必须直接报错**（例如 `"error": "mode=cutoff not supported in v1"`），不得假装支持。
- 不接受调用方传入未定义字段；未定义字段应作为错误上报。

---

## 输出结构

Skill 的每次输出都必须由以下三块组成，顺序不得颠倒：

### 1. 稿件正文（必有）

- Markdown 格式。
- **默认不在正文中插入内部 Ref（如 `[[claim-xxx]]`）**；所有证据追溯放到脚注区。
- 严格遵循对应主题的结构模板（见 `references/structure-templates.md`）与字数区间。

### 2. 证据脚注（可选保留，默认附带）

- 以 `---` 分隔线隔开正文。
- 列出稿件中关键结论对应的 `claim_id` / `ev_id` / `source_ref`，格式如：

```
## 证据脚注
- 结论："主角在此役后彻底与师门决裂" → claim-00042（explicit）/ ev-00117 / src: vol-03/ch-0085:L120-L138
- 结论："A 对 B 存在明显庇护倾向" → claim-00088（reported）/ ev-00201 / src: vol-04/ch-0112:L45-L60
- 版本冲突说明（如有）：claim-00042 曾有旧版结论"因家族压力离开"，已采用较新 revision。
```

- 调用方若指定 `include_footnotes=false`，可剥离此块；但 Skill 默认保留。

### 3. 元信息（必有）

- 用 fenced YAML 或 JSON 代码块呈现，便于下游解析：

```yaml
meta:
  task_type: chapter_explanation
  subject_refs: [char-00001, char-00017]
  focus_ranges: [{from: ch-0081, to: ch-0100}]
  as_of: ch-0100              # 本次解说叙述到达的章节位置
  word_count: 2143            # 稿件正文字数（含标点，不含脚注）
  target_word_range: [1500, 2500]
  coverage_gaps:              # 索引覆盖不全或未纳入的范围
    - "ch-0088 ~ ch-0090 的 events 覆盖为 partial，已退回原文核验"
  budget_truncated: false     # 是否因 token_budget 停止扩展
  index_version: 2.0.0
  source_version: 20260301
```

---

## 自检清单（输出前必查）

LLM 在交付前必须完成以下自检；**任一不通过**都要重写或补证：

1. **输入校验**：`novel_root` 可访问；`task_type` 合法；`subject`/`focus_ranges` 符合必填矩阵；无 `mode=cutoff` 等禁用参数。
2. **主体解析**：若 `subject` 为名称字符串，已完成精确匹配且无歧义；否则已向调用方返回歧义列表而非擅自选择。
3. **材料覆盖**：目标范围的 `coverage.topics[task_type]` 不是 `not_analyzed`；若为 `partial`/`stale`，已在 `meta.coverage_gaps` 中标注。
4. **证据对齐**：稿件中每一处客观事实陈述均对应 `claim-*`（explicit/reported）；解读与推断使用解说员口吻且有 explicit 锚点；无索引依据的情绪描写使用"仿佛/或许"等解说腔。
5. **叙述顺序**：涉及 `supersedes_refs` 的事件按信息揭示顺序讲述；`revealed_at` 晚于当前章节位置的结论已明确标注"后来才揭示"。
6. **结构与字数**：段落结构匹配本主题模板；字数在目标区间内，偏差 ≤ 20%；偏差过大则压缩/扩展或改报"材料不足"。
7. **节奏与钩子**：前 100 字内存在至少一个强钩子；主体每 300–500 字至少 1 次节奏变化；全文 ≥ 2 条可独立成段的金句；结尾符合主题（章节剧情/感情线留追更钩子；人物/势力/体系落在余韵式思考）。
8. **只读契约**：本次任务未写入任何索引文件，不触发账本/编号变更。

---

## 文件地图

```
skills/public/novel-narration-generator/
├── SKILL.md                              # 本文件（LLM 入口）
├── references/
│   ├── retrieval-playbook.md             # 五类主题检索指南详解
│   ├── style-guide-chapter.md            # 章节剧情文风（章回体 + 悬念牵引）
│   ├── style-guide-biography.md          # 人物传记文风（人物弧光 + 命运叙事）
│   ├── style-guide-faction.md            # 势力格局文风（棋局推演 + 利益分析）
│   ├── style-guide-worldbuilding.md      # 体系设定文风（纪录片 + 爽文解构）
│   ├── style-guide-emotion.md            # 感情线文风（心流叙事 + 情感考古）
│   ├── structure-templates.md            # 五类稿件的结构模板与字数区间
│   └── evidence-and-boundary.md          # 证据追溯与边界情况处理
└── examples/
    ├── example-chapter.md
    ├── example-biography.md
    ├── example-faction.md
    ├── example-worldbuilding.md
    └── example-emotion.md
```

**加载顺序建议**：主流程启动 → `retrieval-playbook.md` → `evidence-and-boundary.md` → 对应主题的 `style-guide-*.md` → `structure-templates.md` → 示例稿（可选参照）。

---

## 版本记录

- **v1.0.0**（当前）：首发版本。支持五类解说、一期视角 `mode=full`、纯只读消费端。向后兼容承诺：输入契约字段不缩减、不改语义；新增字段只做可选参数。
