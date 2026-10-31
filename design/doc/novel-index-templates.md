# 长篇小说按需索引：文件结构与生成模板

- 模板版本：`2.0`；与1.0存在字段和语义变更，旧数据需显式迁移，不能只改版本号。
- 适用规模：约 600 万字的单部长篇小说，章节数以原文清单为准。
- 目标：为章节剧情、人物传记、势力格局、体系设定、人物关系、感情线解析提供可按需加载的材料。
- 原文策略：允许按需回读；普通证据章级可回溯，关键结论增加锚点。
- 一期视角：全书复盘 `full`；严格截止 `cutoff` 为附录 A 的二期可选能力，未实现、不承诺防剧透。
- 交付边界：本文包含文件模板及执行协议，不是已实现的解析器、账本执行器、检索服务或 JSON Schema；前后端代码均无改动。

## 1. 使用方式与基本原则

### 1.1 如何套用模板

1. 先建立原文清单，确定全书连续章节号及原文版本。
2. 从本文件选取对应的文件模板；同类索引复用通用结构，不自行发明字段。
3. 替换小说 ID、记录 ID、标题、路径、章节范围及内容。示例 ID 和示例内容不能直接写入真实小说。
4. 没有内容时不创建空实体或空感情线。尚未分析与分析后未发现内容由覆盖记录区分。
5. 新记录必须能够通过导航找到；多个主题引用同一个事件，不各写一份事实。
6. 重要分析回到原文核验，摘要不是最终事实来源。

本文 JSON 代码块均采用合法 JSON，不使用注释、尾逗号或 `...`。有些代码块是公共子结构，有些是完整文件；以所在小节说明为准。字段表中未标注“可选”的字段必须存在。

### 1.2 最小规模与扩容

- 导航只负责定位，摘要只负责帮助判断是否需要深入阅读。
- 事件记录关键行动、选择、转折和结果，不给每个普通动作单独建档。
- 人物、势力只有出现持续经历时才拆分阶段；短暂出场者可以只有实体入口和事件引用。
- 原文按章保存；导航与事件集合按大小分片；人物和关系按经历阶段组织。
- 存储分片不等于剧情阶段。一个事件可以跨章节、跨卷，不因分片改变 ID。
- 原文和事实提取允许修正；修正必须保留依据与关联，不能用后文认识无痕改写前文记录。

### 1.3 示例说明

全文使用下列**虚构的两段原文**解释模板，不对应任何真实小说：

> 第 1 段：在溪边，沈岚把听风术的口诀交给林舟，说：“先静心，才听得清。”
>
> 第 2 段：沈岚又说：“我来自青竹书院。你尚未入院，今日只是初识。”林舟向她道谢。

示例可明确支持“交付口诀”“道谢”；“静心是条件”“来自书院”首先属于沈岚的说法，不能自动当作普遍规则或客观身份。此时也不能据此确认正式师徒关系或爱情。

## 2. 目录及模板对照

以下是未来小说数据根目录 `novel/`，本轮不实际创建：

```text
novel/
├── manifest.json
├── retrieval-guide.md
├── navigation/
│   ├── catalog.json
│   ├── task-routes.json
│   ├── chapters/index.json
│   ├── chapters/block-0001.json
│   ├── names/index.json
│   └── names/part-0001.json
├── source/
│   ├── index.json
│   └── vol-001/
│       ├── index.json
│       └── ch-000001.txt
├── plot/
│   ├── index.json
│   ├── arcs/arc-001.md
│   └── chapters/ch-000001.md
├── events/
│   ├── index.json
│   └── block-0001.json
├── characters/
│   ├── index.json
│   └── char-0001/
│       ├── index.json
│       └── stages/stage-001.md
├── factions/
│   ├── index.json
│   ├── fac-0001/index.json
│   ├── fac-0001/stages/stage-001.md
│   └── landscape/stage-001.md
├── settings/
│   ├── index.json
│   └── entries/setting-0001.json
├── relationships/
│   ├── index.json
│   ├── by-character/char-0001.json
│   └── pairs/rel-0001.json
├── emotions/
│   ├── index.json
│   └── emo-0001/
│       ├── index.json
│       └── stages/stage-001.md
├── threads/
│   ├── index.json
│   └── thread-0001.json
├── ledger/
│   ├── id-state.json
│   └── chapters/ch-000001.json
└── quality/
    ├── coverage.json
    ├── coverage/block-0001.json
    ├── issues.json
    ├── issues/block-0001.json
    ├── benchmarks/run-0001.json
    └── audits/batch-0001.json
```

`navigation/` 另含 `stage-plan.json`，保存精读前确认的阶段骨架。原文、事件、覆盖和问题按范围分片；账本按章保存。下列新增路径均为未来数据模板，不代表已创建执行器或实际数据。

| 新增规划路径 | kind | 模板 |
|---|---|---|
| `ledger/id-state.json` | `id_state` | §11.4 |
| `ledger/chapters/*.json` | `chapter_ledger` | §11.5 |
| `navigation/stage-plan.json` | `stage_plan` | §11.1 |
| `quality/benchmarks/*.json` | `benchmark` | §9.4 |
| `quality/audits/*.json` | `audit` | §11.6 |

| 路径或路径类型 | 文件 `kind` | 模板 |
|---|---|---|
| `manifest.json` | `manifest` | §4.1 |
| `retrieval-guide.md` | 不属于小说内容文件 | §9 |
| `navigation/catalog.json` | `index` | §3.7、§4.2 |
| `navigation/task-routes.json` | `task_routes` | §9.1 |
| `navigation/chapters/index.json` | `index` | §3.7 |
| `navigation/chapters/block-*.json` | `index` | §4.3 |
| `navigation/names/index.json` | `name_catalog` | §4.4 |
| `navigation/names/part-*.json` | `name_lookup` | §4.5 |
| `source/index.json` | `index` | §3.7 |
| `source/<卷>/index.json` | `source_chapters` | §5 |
| `plot/index.json` | `index` | §3.7 |
| `plot/arcs/*.md` | `arc_summary` | §7.1 |
| `plot/chapters/*.md` | `chapter_summary` | §7.1 |
| `events/index.json`（仅块级入口） | `index` | §3.7、§11.2 |
| `events/block-*.json` | `event_collection` | §6 |
| 六类主题的根 `index.json` | `index` | §3.7 |
| 人物、势力的实体 `index.json` | `entity_index` | §7.2 |
| 人物、势力阶段 Markdown | `character_stage` / `faction_stage` | §7.1、§7.2 |
| `factions/landscape/*.md` | `faction_landscape` | §7.1 |
| `settings/entries/*.json` | `setting` | §7.3 |
| `relationships/by-character/*.json` | `index` | §3.7、§7.4 |
| `relationships/pairs/*.json` | `relationship` | §7.4 |
| 感情线的实体 `index.json` | `emotional_index` | §7.5 |
| 感情线阶段 Markdown | `emotional_stage` | §7.1、§7.5 |
| `threads/index.json` | `index` | §3.7 |
| `threads/thread-*.json` | `story_thread` | §8.1 |
| `quality/coverage.json`、`quality/issues.json` | `index` | §3.7 |
| 覆盖与问题分片 | `coverage` / `issue_collection` | §8.2、§8.3 |

剧情、人物、势力及关系材料都引用 §11.1 预扫描确认的阶段骨架；主体只创建相关阶段的材料，具体参与范围可以不同。Markdown 与关系快照通过 stage_ref 明确归属，不以文件名推断，也不在精读中临时切分阶段。

## 3. 全部模板共享的协议

### 3.1 公共文件头 `FileMeta`

除原始 `.txt` 和操作说明 `retrieval-guide.md` 外，每个 JSON 文件及剧情 Markdown 的 Front Matter 都具有：

| 字段 | 类型 | 含义 |
|---|---|---|
| `schema_version` | string | 当前为 `2.0` |
| `novel_id` | string | 小说 ID，同一索引库保持一致 |
| `id` | string | 文件主记录 ID |
| `kind` | string | §2 表中对应类型，不使用自由文本 |
| `revision` | integer | 内容版本，初始为 1，实际修改才递增 |
| `safe_through` | integer | 整份内容包含的信息所需的最晚揭示章，无剧情内容为 0 |

`safe_through=120` 提示本文件的标题、摘要、身份对应或结论涉及最晚第120章揭示的信息，不是访问授权或防剧透保证。一期不据此裁剪输入，标错则通过 §11.6 审计修正。

- 它不表示已完整分析到哪一章，覆盖情况另查 coverage。
- 只描述当前文件自身内容，不递归取所有引用目标的最大值；引用关系本身透露的剧情仍计入。
- `revealed_at` 保留用于讲述信息揭示顺序；历史认识不能被后文结论无痕覆盖。
- 账本、阶段计划、基准和审计等运行文件不作为解说默认材料；含剧情时也需填写相应提示。

### 3.2 空值、编号与命名

| 表达 | 含义 |
|---|---|
| `null` | 字段适用，但当前未知或没有可靠值 |
| `[]` | 当前条目没有对应内容；是否检查过看覆盖状态 |
| 字段省略 | 仅限字段表明确标为可选的字段 |
| 空字符串 | 不用于代替未知 |

- 全书章节顺序号从 1 连续递增，不使用原书可能重复的“第一章”作为唯一编号。
- 章节 ID 如 `ch-000001`；人物 `char-0001`；势力 `fac-0001`；设定 `setting-0001`；事件 `ev-0001`。
- 关系 `rel-0001`；感情线 `emo-0001`；故事线 `thread-0001`；陈述 `claim-0001`；更新 `update-0001`；问题 `issue-0001`。
- 文档 ID 如 `doc-char-0001-stage-001`；索引集合 ID 如 `idx-characters`。
- ID 在小说内唯一。引用中的重复 ID 是引用，不是新定义。
- 路径与 ID 不随人物改名、身份揭示或阶段延长而改变。不得以“幕后真凶”等未来身份作为路径名。
- 示例编号只演示格式。实际按 §11.4 预留编号并写入 §11.5 章节账本；恢复时复用，不回收空号，不要求 LLM 计算散列。

### 3.3 引用 `Ref`

公共子结构：

```json
{
  "path": "events/block-0001.json",
  "record_id": "ev-0001"
}
```

| 字段 | 类型 | 规则 |
|---|---|---|
| `path` | string | 相对 `novel/` 的路径，使用 `/` |
| `record_id` | string | 文件根记录或内部唯一记录 ID |

不得使用绝对路径、`..`、外部 URL；读取程序还须检查解析后的真实路径，防止符号链接绕过根目录限制。定位集合内记录时按 ID 查找，不使用易变化的数组下标。

JSON 字段以 `*_ref` / `*_refs` 表示 `Ref` / `Ref[]`。`source_refs` 专门使用下一节的 `SourceRef[]`。物理分片允许迁移，但必须同时更新引用；不因某个主题进入新阶段就迁移共享事件。

### 3.4 章节范围与原文引用

`ChapterRange` 为包含首尾的范围。多个范围必须升序、无重叠，并合并相邻范围：

```json
{
  "start": 1,
  "end": 12
}
```

`chapter_ranges` 表示内容涉及或被叙述的章节位置，不自动表示身份生效期、故事内部时间或读者获知时间。

`SourceRef` 默认只定位到章：

```json
{
  "path": "source/vol-001/ch-000001.txt",
  "chapter_id": "ch-000001",
  "chapter_order": 1
}
```

| 字段 | 类型 | 必填性与语义 |
|---|---|---|
| `path` | string | 必填，相对原文路径 |
| `chapter_id`、`chapter_order` | string、正整数 | 必填，与原文清单一一对应 |
| `source_version` | string | 可选；省略时继承本数据集绑定的原文版本 |
| `locator` | object | 可选，仅 `{type: paragraph_range, start: 正整数, end: 正整数}` |
| `anchor` | string | 可选，准确且可定位的原文短片段，可以独立于 locator 使用 |

普通陈述章级可回溯即可。反转、争议、身份揭示和关键定性结论至少为关键依据保留 anchor；需要精确范围时再加 locator。没有可靠锚点时保留章级入口并记录证据缺口，不捏造定位。

```json
{
  "path": "source/vol-001/ch-000001.txt",
  "chapter_id": "ch-000001",
  "chapter_order": 1,
  "anchor": "我来自青竹书院。"
}
```

- 三个可选字段不用 null 占位；删除旧的 `locator.type=text_anchor` 联合形式，迁移为独立 anchor。
- 导入使用 UTF-8 与 LF；段落按空行分隔的非空块从1编号，范围闭区间。锚点须在所指章或段落范围唯一匹配，否则扩大上下文并复核。
- 数据集绑定版本不可原位切换；原文变化须建立新数据版本、显式迁移关联记录与账本。省略 source_version 不能使旧引用悄悄继承新版原文。
- 不保存整章引文副本；原文允许按需重复读取。

### 3.5 原子陈述 `Claim`

事件和结构化主题记录内保存陈述；Markdown 引用这些陈述，不再建立另一份权威事实。

```json
{
  "id": "claim-0001",
  "text": "沈岚把听风术的口诀交给林舟。",
  "certainty": "explicit",
  "attributed_to_ref": null,
  "revealed_at": 1,
  "source_refs": [
    {
      "path": "source/vol-001/ch-000001.txt",
      "chapter_id": "ch-000001",
      "chapter_order": 1
    }
  ],
  "basis_refs": [],
  "supersedes_refs": []
}
```

| 字段 | 类型 | 语义 |
|---|---|---|
| `id` | string | 陈述唯一 ID |
| `text` | string | 一条可核验的陈述，不混合多个无关结论 |
| `certainty` | enum | `explicit` / `reported` / `inferred` / `uncertain` |
| `attributed_to_ref` | Ref 或 null | 说法来源；无法识别或解析者推断为 null |
| `revealed_at` | integer | 当前完整表述及确定性得到依据的最早章节 |
| `source_refs` | SourceRef[] | 原文依据 |
| `basis_refs` | Ref[] | 所依据的已有陈述 |
| `supersedes_refs` | Ref[] | 本条修正或取代的旧陈述 |

确定性规则：

- `explicit`：原文明确发生的行为或由可靠叙述直接支持的内容。角色说出某句话是事实，但话的内容未必是事实。
- `reported`：角色、传闻或文内资料的说法，保留来源与语境。
- `inferred`：解析归纳，必须有 `source_refs` 或 `basis_refs`，不能凭空补齐。
- `uncertain`：依据不足或多种理解并存。不要用一个概率数字替代歧义说明。

每条陈述至少有原文依据或已有陈述依据。`basis_refs` 不形成循环。`revealed_at` 不得早于其所需依据的揭示章；后文才证实的解释，不能因为它解释的是前文，就回填为前文已知。

后文推翻旧说法时新增陈述并设置 `supersedes_refs`，保留原说法与修正依据；解说可结合后文，但不得把后来确认的真相说成当时人物已经知道。

同一个 `Claim` 只定义一次。公共结构示例与后文事件示例是同一模板实例，不应分别导入。

### 3.6 揭示时间与提示

`revealed_at` 表示一项内容得到依据的最早章节，`safe_through` 提示文件或导航项涉及的最晚揭示章。身份、更新和分析中的引用也须纳入时间判断；新增后文解释时追加更新或提高提示值。一期不要求构造历史投影。

### 3.7 通用索引 `IndexFile`

适用于多数 `index.json`、章节导航分片及按人物检索关系的文件。

```json
{
  "schema_version": "2.0",
  "novel_id": "novel-example",
  "id": "idx-characters",
  "kind": "index",
  "revision": 1,
  "safe_through": 1,
  "title": "人物索引",
  "scope": {
    "chapter_ranges": [{ "start": 1, "end": 1 }],
    "subject_refs": []
  },
  "coverage_status": "partial",
  "entries": [
    {
      "target": {
        "path": "characters/char-0001/index.json",
        "record_id": "char-0001"
      },
      "kind": "entity_index",
      "title": "林舟",
      "summary": "溪边相遇中的口诀接受者，可继续查看其经历与相关事件。",
      "chapter_ranges": [{ "start": 1, "end": 1 }],
      "entity_refs": [
        { "path": "characters/char-0001/index.json", "record_id": "char-0001" }
      ],
      "tags": ["character"],
      "safe_through": 1
    }
  ]
}
```

公共文件头之外：

| 字段 | 类型 | 规则 |
|---|---|---|
| `title` | string | 索引用途，尽量中性 |
| `scope` | object | `chapter_ranges: ChapterRange[]`、`subject_refs: Ref[]` |
| `coverage_status` | enum | `partial` / `complete`，只相对声明范围 |
| `entries` | IndexEntry[] | 导航项 |

`IndexEntry`：

| 字段 | 类型 | 规则 |
|---|---|---|
| `target` | Ref | 唯一目标；同一索引内按 path + record_id 去重 |
| `kind` | string | 目标实际类型；指向通用下级索引时为 `index` |
| `title` | string | 用于检索的简短名称 |
| `summary` | string | 建议≤60个 Unicode 码点，硬上限120；含标点与空白，超限重新概括，不机械截断 |
| `chapter_ranges` | ChapterRange[] | 可检索的关联范围 |
| `entity_refs` | Ref[] | 对应主体，身份关联保留揭示依据 |
| `tags` | string[] | §3.8 中的分类标签 |
| `safe_through` | integer | 本导航项自身全部信息的揭示范围提示 |

IndexEntry 共8个字段，不持久化 Token 估算。索引自身 safe_through 不低于所含项的最大值，但不递归传播目标文件的值；这是提示信息，不是一期开启严格筛选的条件。

### 3.8 首版受控值

为避免模型写出互不兼容的字段，首版限定以下值；不够用时保留具体原文描述并升级模板，不临时改变含义。

| 字段 | 允许值 |
|---|---|
| `tags` | `plot`、`character`、`faction`、`setting`、`relationship`、`emotion`、`event`、`thread`、`source`、`quality` |
| 事件参与角色 `role` | `initiator`、`participant`、`recipient`、`witness`、`affected`、`mentioned`、`unknown` |
| 设定 `category` | `power_system`、`ability`、`artifact`、`geography`、`species`、`social_rule`、`other` |
| 关系维度 `type` | `kinship`、`instruction`、`friendship`、`romance`、`cooperation`、`hostility`、`membership`、`other` |
| 感情线 `category` | `romantic`、`familial`、`friendship`、`mixed`、`uncertain` |
| 主题覆盖键 | `plot`、`characters`、`factions`、`settings`、`relationships`、`emotions`、`events`、`threads` |

`other` 不是丢弃信息，原文内容仍保存在陈述中。受控分类服务检索，不代替小说自己的术语。

## 4. 入口与导航模板

### 4.1 `manifest.json`

```json
{
  "schema_version": "2.0",
  "novel_id": "novel-example",
  "id": "manifest",
  "kind": "manifest",
  "revision": 1,
  "safe_through": 0,
  "title": "示例小说",
  "author": null,
  "language": "zh-CN",
  "source_version": "source-v1",
  "catalog_ref": { "path": "navigation/catalog.json", "record_id": "idx-catalog" },
  "source_index_ref": { "path": "source/index.json", "record_id": "idx-source" },
  "chapter_index_ref": { "path": "navigation/chapters/index.json", "record_id": "idx-chapters" },
  "name_index_ref": { "path": "navigation/names/index.json", "record_id": "idx-names" },
  "task_routes_ref": { "path": "navigation/task-routes.json", "record_id": "task-routes" },
  "coverage_ref": { "path": "quality/coverage.json", "record_id": "idx-coverage" },
  "issues_ref": { "path": "quality/issues.json", "record_id": "idx-issues" },
  "id_state_ref": { "path": "ledger/id-state.json", "record_id": "id-state" },
  "stage_plan_ref": { "path": "navigation/stage-plan.json", "record_id": "stage-plan" },
  "chapter_ledger_directory": "ledger/chapters/",
  "published_through": 0,
  "retrieval_guide_path": "retrieval-guide.md"
}
```

`author` 可为 null，其余业务字段必填。不保存最新剧情、角色结局或全书摘要。

- `source_version` 是本索引数据集绑定的原文版本；同一数据集内不可原位切换为另一版本，版本变更需显式迁移或重建。
- `published_through` 是完成账本提交与覆盖发布的连续章节前缀，非负整数，初始为 0；不等于各主题均无缺口，质量仍查 coverage。
- `chapter_ledger_directory` 下用章节 ID 定位账本，例如 `ch-000001.json`；账本根 ID 为 `ledger-ch-000001`。账本是运行材料，不在默认解说导航中全文加载。
- 原文版本与发布进度不能证明全书已索引完整。只有原文清单所有目标章节完成后才能称全书完成。

### 4.2 `navigation/catalog.json`

复用 `IndexFile`，`id=idx-catalog`，`title=主题导航`。`scope` 两个数组可为空，表示不按剧情范围限定；`coverage_status=complete` 仅表示本导航已列齐约定入口。

每一行实例化为一个 `IndexEntry`，名称和摘要只描述用途，`safe_through=0`，`chapter_ranges=[]`，`entity_refs=[]`：

| 目标 path | 目标 record_id | title / summary | tags |
|---|---|---|---|
| `plot/index.json` | `idx-plot` | 章节剧情 / 按阶段和章节定位剧情材料 | `plot` |
| `characters/index.json` | `idx-characters` | 人物传记 / 按人物和经历阶段定位材料 | `character` |
| `factions/index.json` | `idx-factions` | 势力格局 / 查询势力资料与阶段格局 | `faction` |
| `settings/index.json` | `idx-settings` | 体系设定 / 查询定义、条件、限制与例外 | `setting` |
| `relationships/index.json` | `idx-relationships` | 人物关系 / 查询双方关系及变化 | `relationship` |
| `emotions/index.json` | `idx-emotions` | 感情线 / 查询互动、心理与情感转折 | `emotion` |
| `events/index.json` | `idx-events` | 共享事件 / 查询跨主题引用的剧情事件 | `event` |
| `threads/index.json` | `idx-threads` | 故事线 / 查询主支线、谜团与伏笔 | `thread` |

以上目标 `kind` 均为 `index`。只将表格真正实例化之后，才能声称文件已经存在。

### 4.3 `navigation/chapters/`

- `index.json` 采用 `IndexFile`，入口只列章节分片，范围如 1—50、51—100。
- `block-0001.json` 也采用 `IndexFile`，其 `entries` 逐章指向 `chapter_summary`。
- 章节标题可能泄露剧情，不能默认所有章节导航都是 `safe_through=0`。

章节分片中的一条 `IndexEntry`：

```json
{
  "target": { "path": "plot/chapters/ch-000001.md", "record_id": "doc-ch-000001" },
  "kind": "chapter_summary",
  "title": "第1章：溪边初见",
  "summary": "林舟得到听风术口诀，并听到沈岚对入门条件及自身来历的说明。",
  "chapter_ranges": [{ "start": 1, "end": 1 }],
  "entity_refs": [
    { "path": "characters/char-0001/index.json", "record_id": "char-0001" },
    { "path": "characters/char-0002/index.json", "record_id": "char-0002" }
  ],
  "tags": ["plot"],
  "safe_through": 1
}
```

### 4.4 `navigation/names/index.json`

此入口只列物理分片，不把所有人物姓名放进顶层。首版允许读取程序在分片中精确查找规范化名称，不要求 LLM 逐片全文阅读。

```json
{
  "schema_version": "2.0",
  "novel_id": "novel-example",
  "id": "idx-names",
  "kind": "name_catalog",
  "revision": 1,
  "safe_through": 0,
  "normalization": "nfkc_trim",
  "match_mode": "exact",
  "shard_refs": [
    { "path": "navigation/names/part-0001.json", "record_id": "names-part-0001" }
  ]
}
```

- `normalization` 固定为 Unicode NFKC 后去首尾空白；不擅自繁简转换、不去掉名称内部字符。
- `match_mode` 固定为 `exact`；别名通过显式匹配记录收录。
- 不认识的称呼返回未命中或候选，不自动模糊匹配到最像的名字。
- 后续分片增多时，可由读取程序建立名称到分片的派生查找表，不更改下层名称记录语义。

### 4.5 `navigation/names/part-0001.json`

```json
{
  "schema_version": "2.0",
  "novel_id": "novel-example",
  "id": "names-part-0001",
  "kind": "name_lookup",
  "revision": 1,
  "safe_through": 1,
  "entries": [
    {
      "normalized_name": "林舟",
      "matches": [
        {
          "surface": "林舟",
          "entity_ref": { "path": "characters/char-0001/index.json", "record_id": "char-0001" },
          "entity_type": "character",
          "name_type": "name",
          "identity_status": "confirmed",
          "chapter_ranges": [{ "start": 1, "end": 1 }],
          "revealed_at": 1,
          "source_refs": [
            {
              "path": "source/vol-001/ch-000001.txt",
              "chapter_id": "ch-000001",
              "chapter_order": 1,
              "source_version": "source-v1",
              "locator": { "type": "paragraph_range", "start": 1, "end": 1 },
              "anchor": "沈岚把听风术的口诀交给林舟"
            }
          ],
          "basis_refs": []
        }
      ]
    }
  ]
}
```

`matches` 是候选数组，不能假设只有一个人使用某个称号。

| 字段 | 允许值或说明 |
|---|---|
| `entity_type` | `character` / `faction` / `setting` |
| `name_type` | `name` / `alias` / `title` / `disguise` / `former_name` |
| `identity_status` | `confirmed` / `candidate` |
| `revealed_at` | 名称与该实体的对应关系获知章，不只是这个名字首次出现章 |
| `source_refs`、`basis_refs` | 至少一个非空；依据应支持名称匹配 |

所有实际出现的名字分别建立匹配项，包括“沈岚”“青竹书院”“听风术”；此例只展示一项。

如果“黑衣人”与“林舟”早期不能确认相同，先建两个临时实体。后文通过 §7.2 的 `identity_links` 记录同一身份的揭示，不把历史引用全部重定向到后来确认的实体。读取方在已发布材料范围内解析身份链接。

## 5. 原文清单模板

`source/index.json` 复用 `IndexFile`，每项指向一个卷的 `source_chapters`。无正式分卷的小说使用一个逻辑卷 `vol-001`，不编造书内卷名。

`source/vol-001/index.json`：

```json
{
  "schema_version": "2.0",
  "novel_id": "novel-example",
  "id": "source-vol-001",
  "kind": "source_chapters",
  "revision": 1,
  "safe_through": 1,
  "volume_id": "vol-001",
  "source_version": "source-v1",
  "encoding": "utf-8",
  "normalization": "lf",
  "paragraph_rule": "blank_line_separated",
  "chapters": [
    {
      "id": "ch-000001",
      "chapter_order": 1,
      "title": "溪边初见",
      "path": "source/vol-001/ch-000001.txt",
      "safe_through": 1,
      "sha256": null,
      "paragraph_count": 2
    }
  ]
}
```

- `chapters[].id` 是章节 ID；章节摘要有独立文档 ID，不能混用。
- `title` 允许 null；`sha256` 为程序计算的字符串或 null，不让模型编造。
- `paragraph_count` 为程序统计的非负整数或 null。
- 清单与原文由导入流程维护；生成主题索引不改写原文。
- 一份原文文件对应一章，不将后文补注、下一章预告或编辑说明混入前章正文；无法分离时应提高其安全边界并报告问题。
- 原文首次出现的语句只证明截至该章可知的信息，不含解析者从外部知识补充的结论。

## 6. 共享事件模板

### 6.1 为什么采用“事件 + 分次更新”

同一事件跨多个章节时保留一个 `ev-*` ID，追加 `updates`。这样后文结果不会覆盖最初经过；截止第 N 章时可以只读取可见更新。

事件名称使用初次出现时已知的中性描述，不从“溪边相遇”改成“幕后安排的收徒骗局”。后来的解释进入新陈述。

### 6.2 `events/block-0001.json`

```json
{
  "schema_version": "2.0",
  "novel_id": "novel-example",
  "id": "events-block-0001",
  "kind": "event_collection",
  "revision": 1,
  "safe_through": 1,
  "events": [
    {
      "id": "ev-0001",
      "kind": "event",
      "title": "溪边交付口诀",
      "introduced_at": 1,
      "safe_through": 1,
      "updates": [
        {
          "id": "update-0001",
          "chapter_ranges": [{ "start": 1, "end": 1 }],
          "revealed_at": 1,
          "status": "completed",
          "story_time": null,
          "summary": "沈岚交付口诀并说明静心要求，林舟向她道谢。",
          "participants": [
            {
              "entity_ref": { "path": "characters/char-0002/index.json", "record_id": "char-0002" },
              "role": "initiator"
            },
            {
              "entity_ref": { "path": "characters/char-0001/index.json", "record_id": "char-0001" },
              "role": "recipient"
            }
          ],
          "claims": [
            {
              "id": "claim-0001",
              "text": "沈岚把听风术的口诀交给林舟。",
              "certainty": "explicit",
              "attributed_to_ref": null,
              "revealed_at": 1,
              "source_refs": [
                {
                  "path": "source/vol-001/ch-000001.txt",
                  "chapter_id": "ch-000001",
                  "chapter_order": 1
                }
              ],
              "basis_refs": [],
              "supersedes_refs": []
            },
            {
              "id": "claim-0002",
              "text": "按沈岚的说法，练习听风术需要先静心。",
              "certainty": "reported",
              "attributed_to_ref": { "path": "characters/char-0002/index.json", "record_id": "char-0002" },
              "revealed_at": 1,
              "source_refs": [
                {
                  "path": "source/vol-001/ch-000001.txt",
                  "chapter_id": "ch-000001",
                  "chapter_order": 1,
                  "source_version": "source-v1",
                  "locator": { "type": "paragraph_range", "start": 1, "end": 1 },
                  "anchor": "先静心，才听得清。"
                }
              ],
              "basis_refs": [],
              "supersedes_refs": []
            },
            {
              "id": "claim-0003",
              "text": "沈岚自称来自青竹书院。",
              "certainty": "reported",
              "attributed_to_ref": { "path": "characters/char-0002/index.json", "record_id": "char-0002" },
              "revealed_at": 1,
              "source_refs": [
                {
                  "path": "source/vol-001/ch-000001.txt",
                  "chapter_id": "ch-000001",
                  "chapter_order": 1,
                  "source_version": "source-v1",
                  "locator": { "type": "paragraph_range", "start": 2, "end": 2 },
                  "anchor": "我来自青竹书院。"
                }
              ],
              "basis_refs": [],
              "supersedes_refs": []
            },
            {
              "id": "claim-0004",
              "text": "林舟向沈岚道谢。",
              "certainty": "explicit",
              "attributed_to_ref": null,
              "revealed_at": 1,
              "source_refs": [
                {
                  "path": "source/vol-001/ch-000001.txt",
                  "chapter_id": "ch-000001",
                  "chapter_order": 1
                }
              ],
              "basis_refs": [],
              "supersedes_refs": []
            }
          ],
          "trigger_refs": [],
          "action_refs": [
            { "path": "events/block-0001.json", "record_id": "claim-0001" }
          ],
          "outcome_refs": [
            { "path": "events/block-0001.json", "record_id": "claim-0004" }
          ],
          "related_event_refs": []
        }
      ]
    }
  ]
}
```

### 6.3 字段约束

`event_collection` 在公共文件头之外只包含 `events: Event[]`。其中 `Event` 是嵌入记录，不重复文件头：

| Event 字段 | 类型 | 说明 |
|---|---|---|
| `id`、`kind` | string | 唯一事件 ID；kind 固定为 `event` |
| `title` | string | 初次建档时已知的中性名称 |
| `introduced_at` | integer | 首次获知本事件的章节 |
| `safe_through` | integer | 事件全部内容的最大揭示边界 |
| `updates` | EventUpdate[] | 按揭示章排序，非空 |

`EventUpdate`：

- `id`、`chapter_ranges`、`revealed_at`、`summary` 必填。
- `status`：`ongoing` / `completed` / `unknown`，表示截至这次更新的已知进展。
- `story_time`：string 或 null，仅填写原文可支持的时间描述，如“三日前”；不要把阅读顺序当成故事时间。
- `participants`：`{entity_ref: Ref, role: enum}[]`；角色只限本次更新已知信息。
- `claims: Claim[]`：本次新提取或修正的陈述，已有陈述以引用复用。
- `trigger_refs`、`action_refs`、`outcome_refs`：指向 `Claim`，分别组织起因、经过和结果。时间相邻不自动产生因果。
- `related_event_refs`：其他事件，只表示相关，不代表因果。

一次更新不能夹带更晚揭示的信息。事件根 `safe_through` 不小于 `introduced_at` 及所有更新的 `revealed_at`；集合文件不小于所有事件的边界。

独立行动应创建新事件，长期目标用故事线串联。事件完成后再被回忆或揭示新信息仍可追加更新，但不能把认识变化伪装成事件重新发生。

## 7. 六类主题模板

### 7.1 通用 Markdown 材料

适用于章节、剧情阶段、人物阶段、势力阶段、格局概览和感情阶段。下面是一个**完整的章节摘要示例**：

````markdown
---
schema_version: "2.0"
novel_id: novel-example
id: doc-ch-000001
kind: chapter_summary
revision: 1
safe_through: 1
title: 第1章：溪边初见
chapter_ranges:
  - start: 1
    end: 1
as_of: 1
stage_ref:
  path: navigation/stage-plan.json
  record_id: stage-001
subject_refs:
  - path: characters/char-0001/index.json
    record_id: char-0001
  - path: characters/char-0002/index.json
    record_id: char-0002
record_refs:
  - path: events/block-0001.json
    record_id: ev-0001
  - path: events/block-0001.json
    record_id: claim-0001
  - path: events/block-0001.json
    record_id: claim-0002
  - path: events/block-0001.json
    record_id: claim-0003
  - path: events/block-0001.json
    record_id: claim-0004
source_refs:
  - path: source/vol-001/ch-000001.txt
    chapter_id: ch-000001
    chapter_order: 1
---

# 第1章：溪边初见

## 开始局面
林舟与沈岚在溪边相遇，交付口诀是本章关键事件。[[ev-0001]]

## 关键行动
沈岚把听风术的口诀交给林舟。[[claim-0001]]

## 转折与新信息
沈岚说明静心要求，并自称来自青竹书院；这些说法保留其陈述性质。[[claim-0002]] [[claim-0003]]

## 本章结果
林舟向沈岚道谢。[[claim-0004]]

## 未决问题与补读入口
现有材料未确认林舟已学会听风术，也未确认正式师徒关系。如需判断互动语气，回读本章第1—2段。
````

Front Matter 在公共文件头之外统一包含：

| 字段 | 类型 | 规则 |
|---|---|---|
| `title` | string | 标题受同样的揭示边界约束 |
| `chapter_ranges` | ChapterRange[] | 文档主要分析的剧情范围 |
| `as_of` | integer | 这份摘要采用的知识截止章 |
| `stage_ref` | Ref | 已确认阶段骨架中的归属；主要分析范围必须在该阶段内 |
| `subject_refs` | Ref[] | 分析主体 |
| `record_refs` | Ref[] | 事件、陈述和其他结构化依据 |
| `source_refs` | SourceRef[] | 必要的直接补读位置 |

`as_of` 标明摘要实际使用材料的揭示截止章，需满足 safe_through ≤ as_of；可以晚于主要讲述范围，但必须区分当时所知与后文解释。这是来源一致性要求，不构成防剧透承诺。

`[[ID]]` 必须在 record_refs 显式声明。非感情类文档的新事实或推断先进入相应 claims；感情阶段只组织已有 assessment 和关系阶段，source_refs 为空，经关系回读原文，不重复建立互动事实。

同一公共模板替换 `kind` 后使用以下固定正文结构：

| kind / 用途 | 必备正文小节 |
|---|---|
| `chapter_summary` / 章节剧情 | 开始局面；关键行动；转折与新信息；本章结果；未决问题与补读入口 |
| `arc_summary` / 剧情阶段 | 阶段范围；起始局面；核心目标与冲突；关键转折；阶段结果；下一阶段承接与未决问题 |
| `character_stage` / 人物阶段 | 阶段起点；目标与动机；关键选择与经历；身份与能力变化；认知与性格表现；阶段终点；证据不足与补读入口 |
| `faction_stage` / 势力阶段 | 性质与结构；已知成员及依据；资源与范围；目标与利益；合作与冲突；阶段变化；未确认信息 |
| `faction_landscape` / 格局概览 | 参与势力；利益与资源分布；合作关系；冲突焦点；格局转折事件；仍不能判断的部分 |
| `emotional_stage` / 感情阶段 | 分析结论；变化解释；关系阶段引用；推断边界 |

小节无可用材料时注明“本范围尚未提取到依据”，不写想象补全。不存在的详细心理、势力资源和爱情动机都不是必须填满的字段。

### 7.2 人物与势力入口 `entity_index`

人物和势力复用一个结构。实体 ID 就是入口文件的根 ID；它是实体的固定地址，而不是会随阶段变化的档案路径。

`characters/char-0001/index.json`：

```json
{
  "schema_version": "2.0",
  "novel_id": "novel-example",
  "id": "char-0001",
  "kind": "entity_index",
  "revision": 1,
  "safe_through": 1,
  "entity_type": "character",
  "label": "林舟",
  "introduced_at": 1,
  "identity_notes": [],
  "identity_links": [],
  "related_materials": [
    {
      "topic": "events",
      "target": { "path": "events/block-0001.json", "record_id": "ev-0001" },
      "revealed_at": 1
    },
    {
      "topic": "relationships",
      "target": { "path": "relationships/by-character/char-0001.json", "record_id": "idx-rel-char-0001" },
      "revealed_at": 1
    }
  ],
  "entries": [
    {
      "target": { "path": "characters/char-0001/stages/stage-001.md", "record_id": "doc-char-0001-stage-001" },
      "kind": "character_stage",
      "title": "溪边初识阶段",
      "summary": "从获得口诀的经历进入本阶段材料。",
      "chapter_ranges": [{ "start": 1, "end": 1 }],
      "entity_refs": [
        { "path": "characters/char-0001/index.json", "record_id": "char-0001" }
      ],
      "tags": ["character"],
      "safe_through": 1
    }
  ]
}
```

业务字段：

| 字段 | 类型 | 规则 |
|---|---|---|
| `entity_type` | enum | `character` / `faction` |
| `label` | string | 初次已知的中性显示名；新称号进入名称匹配表 |
| `introduced_at` | integer | 此实体首次出现或被提及章 |
| `identity_notes` | IdentityNote[] | 不属于某个事件的基本身份信息 |
| `identity_links` | IdentityLink[] | 后续确认两个暂存实体相同的依据 |
| `related_materials` | MaterialLink[] | 关联主题入口或重要事件 |
| `entries` | IndexEntry[] | 经历阶段，复用通用索引项 |

`IdentityNote`：`{id: string, revealed_at: integer, claims: Claim[], claim_refs: Ref[]}`。新的非事件身份陈述放 `claims`，已有事件中的身份信息只用 `claim_refs`。

`IdentityLink`：`{target_ref: Ref, identity_status: confirmed|candidate, revealed_at: integer, basis_refs: Ref[]}`。本文件实体与目标之间是否相同，必须有非空依据。候选不可触发合并；确认后的检索按已发布材料范围去重，原始记录仍保留。身份链接不能形成重定向死循环。

`MaterialLink`：`{topic: string, target: Ref, revealed_at: integer}`。topic 限定为八个主题覆盖键之一。链接表示材料关联，不能替代“成员身份已证实”“已相爱”等事实判断。

势力入口 `factions/fac-0001/index.json` 使用同一模板：

- `id=fac-0001`、`entity_type=faction`、`label=青竹书院`。
- 阶段项指向 `factions/fac-0001/stages/stage-001.md`，`kind=faction_stage`。
- 示例势力可通过 `identity_notes[].claim_refs` 引用 `claim-0003`，说明它被沈岚提及；不能因此推断组织规模和实力。
- 格局概览是多主体 Markdown，`subject_refs` 列参与势力，由 `factions/index.json` 直接导航。

只出现一次的人物可令 `entries=[]`，通过 `related_materials` 回读事件，不为凑格式生成空传记。

### 7.3 体系设定 `settings/entries/setting-0001.json`

```json
{
  "schema_version": "2.0",
  "novel_id": "novel-example",
  "id": "setting-0001",
  "kind": "setting",
  "revision": 1,
  "safe_through": 1,
  "label": "听风术",
  "category": "ability",
  "introduced_at": 1,
  "updates": [
    {
      "id": "update-setting-0001-001",
      "revealed_at": 1,
      "chapter_ranges": [{ "start": 1, "end": 1 }],
      "claims": [],
      "definition_refs": [],
      "condition_refs": [
        { "path": "events/block-0001.json", "record_id": "claim-0002" }
      ],
      "limitation_refs": [],
      "cost_refs": [],
      "exception_refs": [],
      "change_refs": [],
      "demonstration_event_refs": [],
      "related_event_refs": [
        { "path": "events/block-0001.json", "record_id": "ev-0001" }
      ],
      "links": []
    }
  ]
}
```

- `label`、`category`、`introduced_at` 必填，含义只能使用初次建档时可知信息。
- `updates` 非空；每次更新必须带 `id`、`revealed_at`、`chapter_ranges`。
- `claims` 只定义本设定特有的新陈述；事件已提取的说法通过引用复用。
- `definition_refs`、`condition_refs`、`limitation_refs`、`cost_refs`、`exception_refs`、`change_refs` 全部指向 `Claim`。
- `demonstration_event_refs` 只收实际使用或展示的事件。本例仅交付口诀，因此为空。
- `related_event_refs` 收其他相关事件，如首次提及、传授或争论。
- `links` 为 `{relation, target_ref, basis_refs}[]`；relation 为 `contains` / `requires` / `above` / `below` / `adjacent_to` / `related_to`，依据非空，target 必须为另一设定。

地点也使用本模板，`category=geography`，避免再建另一套地点 ID。境界高低不能单凭一次战斗胜负推导；人物声称的规则继续保留 `reported`，不能因被放进设定目录就升格为事实。

### 7.4 人物关系 `relationships/pairs/rel-0001.json`

```json
{
  "schema_version": "2.0",
  "novel_id": "novel-example",
  "id": "rel-0001",
  "kind": "relationship",
  "revision": 1,
  "safe_through": 1,
  "introduced_at": 1,
  "subjects": [
    { "path": "characters/char-0001/index.json", "record_id": "char-0001" },
    { "path": "characters/char-0002/index.json", "record_id": "char-0002" }
  ],
  "stages": [
    {
      "id": "rel-0001-stage-001",
      "stage_ref": { "path": "navigation/stage-plan.json", "record_id": "stage-001" },
      "chapter_ranges": [{ "start": 1, "end": 1 }],
      "as_of": 1,
      "revealed_at": 1,
      "summary": "目前有传授口诀与道谢的互动，正式师徒身份尚未确认。",
      "claims": [],
      "facets": [
        {
          "type": "instruction",
          "direction": "directed",
          "from_ref": { "path": "characters/char-0002/index.json", "record_id": "char-0002" },
          "to_ref": { "path": "characters/char-0001/index.json", "record_id": "char-0001" },
          "description": "发生过交付口诀的教学行为，不等于正式师徒。",
          "basis_refs": [
            { "path": "events/block-0001.json", "record_id": "claim-0001" }
          ]
        }
      ],
      "attitudes": [
        {
          "from_ref": { "path": "characters/char-0001/index.json", "record_id": "char-0001" },
          "to_ref": { "path": "characters/char-0002/index.json", "record_id": "char-0002" },
          "description": "林舟表达了谢意；不能据此认定持续信任或依赖。",
          "basis_refs": [
            { "path": "events/block-0001.json", "record_id": "claim-0004" }
          ]
        }
      ],
      "turning_event_refs": [
        { "path": "events/block-0001.json", "record_id": "ev-0001" }
      ]
    }
  ]
}
```

规则：

1. `subjects` 恰好两个不同主体，按 ID 排序用于关系对去重；可以是人物或势力。
2. 同一关系对可同时有亲属、合作、敌对等维度，不为每次变化建立新关系 ID。
3. 快照字段 id、stage_ref、chapter_ranges、as_of、revealed_at、summary、claims、facets、attitudes、turning_event_refs 必填；stage_ref 指向已冻结骨架，分析范围在该阶段内。
4. revealed_at ≤ as_of，快照全部材料在其揭示章已可支持。小变化作为同一 stage_ref 下的新快照更新，旧快照保留；如 rel-0001-stage-001-snapshot-0002，不因此新增规划阶段。感情分析引用所用快照的固定 ID。
5. `facets[].direction` 为 `symmetric` 或 `directed`。对称维度的 from_ref/to_ref 均为 null；有向维度必须是 subjects 中的两个不同主体。
6. `attitudes` 总是有向，只记有依据的表达、心理原文或行为；文内说法仍保留 reported，不把解释变成客观事实。隐含爱慕等情感定性进入感情分析。
7. `basis_refs` 必须非空，指向支持该关系或态度的陈述。romance 仅用于原文明示的关系事实；不能从一方信任推出另一方信任，也不能从保护行为推出爱情。
8. 阶段未覆盖某章时，不用后面的阶段回填；读取较早材料和中间事件、原文。

`relationships/by-character/char-0001.json` 复用 `IndexFile`：scope.subject_refs 限定为该人物，entries 指向关系主记录，目标 kind 为 `relationship`。人物入口链接该文件，避免扫描全书所有关系。

势力间或人物—势力的关系由相应实体的 `related_materials` 指向关系记录；如数量增加，可按相同模板增设主题内分片，不硬塞进 `by-character/`。

### 7.5 感情线入口 `emotions/emo-0001/index.json`

保留关系与感情两种检索入口，但只有一条事实链：原文 → 事件/陈述 → 关系阶段 → 感情分析。关系组织客观互动、已表达态度及已确认关系的依据；感情线只保存情感定性和变化解释，不复存事件正文或互动 Claim。下面演示尚不能定性的分析入口，真实建库不因一次道谢就必须建档。

```json
{
  "schema_version": "2.0",
  "novel_id": "novel-example",
  "id": "emo-0001",
  "kind": "emotional_index",
  "revision": 1,
  "safe_through": 1,
  "label": "林舟与沈岚的互动线",
  "introduced_at": 1,
  "participants": [
    {
      "character_ref": { "path": "characters/char-0001/index.json", "record_id": "char-0001" },
      "revealed_at": 1
    },
    {
      "character_ref": { "path": "characters/char-0002/index.json", "record_id": "char-0002" },
      "revealed_at": 1
    }
  ],
  "assessments": [
    {
      "id": "assessment-emo-0001-001",
      "revealed_at": 1,
      "category": "uncertain",
      "status": "uncertain",
      "relationship_links": [
        {
          "relationship_ref": { "path": "relationships/pairs/rel-0001.json", "record_id": "rel-0001-stage-001" },
          "revealed_at": 1
        }
      ]
    }
  ],
  "entries": [
    {
      "target": { "path": "emotions/emo-0001/stages/stage-001.md", "record_id": "doc-emo-0001-stage-001" },
      "kind": "emotional_stage",
      "title": "初识互动",
      "summary": "记录交付口诀和道谢，不预先认定情感性质。",
      "chapter_ranges": [{ "start": 1, "end": 1 }],
      "entity_refs": [
        { "path": "characters/char-0001/index.json", "record_id": "char-0001" },
        { "path": "characters/char-0002/index.json", "record_id": "char-0002" }
      ],
      "tags": ["emotion"],
      "safe_through": 1
    }
  ]
}
```

- `participants` 至少两个；只说明分析主体，新参与者记录揭示章，不据此确认恋爱关系。
- `assessments` 每项只有 id、revealed_at、category、status、relationship_links 五个字段。category 见 §3.8；status 为 ongoing / closed / uncertain，表示分析线当前状态，而非双方客观关系。
- 每个 assessment.relationship_links 必须非空，目标为具体关系阶段而不是整份关系根；通过阶段的依据继续回溯事件与原文。揭示时间不得早于所依赖关系阶段。
- 多方感情线引用多个关系对的阶段；所有关系主体都应在 participants 中，不能只保留一对而丢掉第三人。
- 新结论追加 assessment，不覆盖旧定性。关闭不代表人物之后不再互动；保护或道谢不自动推出爱情。
- entries 复用 IndexEntry，阶段 Markdown 只写分析，不复制行为、对话或心理原文表。label 用中性名称，不先验定为“命定恋人”。

感情阶段 Markdown 复用 §7.1 元信息，`source_refs=[]`，record_refs 只列 assessment 和关系阶段。固定正文为：**分析结论；变化解释；关系阶段引用；推断边界**。例如：

> 分析结论：现有关系材料不足以定性为爱情。[[assessment-emo-0001-001]]
>
> 变化解释：目前尚无可确认的情感转折，不把单次行为扩展为长期心理。[[rel-0001-stage-001]]
>
> 关系阶段引用：见 [[rel-0001-stage-001]]，经其依据回读事件和原文。
>
> 推断边界：分析属于 uncertain，不能把“未确认爱情”说成“明确没有感情”。

对应 record_refs 分别是 `emotions/emo-0001/index.json#assessment-emo-0001-001` 与 `relationships/pairs/rel-0001.json#rel-0001-stage-001`（实际仍使用两字段 Ref）。分析文字仅解释已有 assessment；新增互动事实必须先归入事件和关系阶段，不能首次出现在感情分析中。

## 8. 辅助故事线与质量模板

### 8.1 `threads/thread-0001.json`

本例将“学习听风术”作为可选支线检索入口，不宣称人物已有明确长期目标。

```json
{
  "schema_version": "2.0",
  "novel_id": "novel-example",
  "id": "thread-0001",
  "kind": "story_thread",
  "revision": 1,
  "safe_through": 1,
  "label": "听风术学习线索",
  "introduced_at": 1,
  "updates": [
    {
      "id": "update-thread-0001-001",
      "revealed_at": 1,
      "chapter_ranges": [{ "start": 1, "end": 1 }],
      "category": "subplot",
      "status": "open",
      "role": "introduction",
      "summary": "出现口诀交付行为，尚未确认后续练习结果。",
      "claims": [],
      "claim_refs": [
        { "path": "events/block-0001.json", "record_id": "claim-0001" }
      ],
      "event_refs": [
        { "path": "events/block-0001.json", "record_id": "ev-0001" }
      ],
      "resolution_refs": []
    }
  ]
}
```

每次更新字段完整且保持历史：

- `category`：`main_plot` / `subplot` / `mystery` / `foreshadowing_candidate` / `foreshadowing_confirmed`。
- `status`：`open` / `progressing` / `resolved` / `unresolved_at_end`。
- `role`：`introduction` / `advance` / `echo` / `reveal` / `resolution`。
- `claims` 定义新的线索判断，`claim_refs` 复用已有判断，两者至少一项非空。
- `resolution_refs` 指向有依据的解决陈述；`status=resolved` 时非空。
- 伏笔先以候选记录，不能因为后文回收就把初期入口名称和类别改成已确认伏笔。
- `unresolved_at_end` 只在全书已完整覆盖且确实完结时使用。

### 8.2 覆盖分片 `quality/coverage/block-0001.json`

```json
{
  "schema_version": "2.0",
  "novel_id": "novel-example",
  "id": "coverage-block-0001",
  "kind": "coverage",
  "revision": 1,
  "safe_through": 0,
  "source_version": "source-v1",
  "chapters": [
    {
      "chapter_id": "ch-000001",
      "chapter_order": 1,
      "topics": {
        "plot": "not_analyzed",
        "characters": "not_analyzed",
        "factions": "not_analyzed",
        "settings": "not_analyzed",
        "relationships": "not_analyzed",
        "emotions": "not_analyzed",
        "events": "not_analyzed",
        "threads": "not_analyzed"
      }
    }
  ]
}
```

本例保持 `not_analyzed`，因为本文没有真的创建小说文件或完成解析。实际生成后，每个主题使用：

| 值 | 含义 |
|---|---|
| `not_analyzed` | 尚未检查 |
| `complete` | 已按当前模板检查并记录发现；不保证理解绝对无误 |
| `no_findings` | 已检查且没有相关信息，不等于没做 |
| `partial` | 有明确遗漏或需要补读 |
| `stale` | 原文或依赖材料变化，需要复核 |

八个主题键必须齐全，不以缺少字段表示“无内容”。覆盖文件不写剧情摘要，可为 `safe_through=0`。一期按任务范围查看已发布覆盖；缺失或 stale 不是已完成。

### 8.3 问题分片 `quality/issues/block-0001.json`

没有问题时 `issues=[]`，下面仅展示问题记录结构，不表示真实发生了定位故障：

```json
{
  "schema_version": "2.0",
  "novel_id": "novel-example",
  "id": "issues-block-0001",
  "kind": "issue_collection",
  "revision": 1,
  "safe_through": 1,
  "issues": [
    {
      "id": "issue-0001",
      "category": "source_locator",
      "severity": "warning",
      "opened_at": 1,
      "safe_through": 1,
      "updates": [
        {
          "revealed_at": 1,
          "status": "open",
          "description": "模板示例：若某条原文锚点不能唯一定位，应重新检查段落范围。",
          "related_refs": [
            { "path": "events/block-0001.json", "record_id": "claim-0001" }
          ],
          "source_refs": [],
          "resolution_refs": []
        }
      ]
    }
  ]
}
```

- `category`：`identity_ambiguity` / `fact_conflict` / `missing_evidence` / `source_locator` / `coverage_gap` / `stale_source`。
- `severity`：`critical` / `warning`。`critical` 阻断发布，需人工介入（写 `quality/issues/` 并进入 review_issues，由人 fixed / skip / stop）；`warning` 非阻断，可由审计分流层自动修复或保留记录，不阻塞 derive。
- `opened_at` 为最初发现对应问题的知识位置；`updates[].revealed_at` 按本次说明内容所需的知识边界填写。
- `status`：`open` / `resolved` / `deferred`；解决时追加更新，不能在旧说明中提前写入后文答案。
- `related_refs` 指向存在的有关记录；`source_refs` 指向需补读的原文；`resolution_refs` 指向修正后的记录或支持消歧的陈述。
- 正常的剧情悬念不是索引质量问题；它们属于故事线。质量问题用于说明提取、消歧、定位或一致性存在缺口。
- 没有依据、未完成和结构错误应如实保留，不能为了让目录看起来完整而编造内容。

## 9. 检索入口与任务模板

### 9.1 `navigation/task-routes.json`

路由文件不包含小说剧情，可整份复用。它描述材料角色与读取顺序，不包含脚本或 Shell 命令。

```json
{
  "schema_version": "2.0",
  "novel_id": "novel-example",
  "id": "task-routes",
  "kind": "task_routes",
  "revision": 1,
  "safe_through": 0,
  "defaults": {
    "max_context_tokens": 12000,
    "task_token_budget": 32000,
    "max_expansion_hops": 1,
    "evidence_policy": "key_claims"
  },
  "routes": [
    {
      "task_type": "chapter_explanation",
      "entry_refs": [
        { "path": "navigation/chapters/index.json", "record_id": "idx-chapters" }
      ],
      "requires_subject": false,
      "required_materials": ["chapter_summary", "event", "source"],
      "optional_materials": ["arc_summary", "entity_index", "setting"],
      "stop_when": "目标章节的主要行动、转折和结果已有依据；缺失前情已补足或明确标注。"
    },
    {
      "task_type": "biography",
      "entry_refs": [
        { "path": "navigation/names/index.json", "record_id": "idx-names" },
        { "path": "characters/index.json", "record_id": "idx-characters" }
      ],
      "requires_subject": true,
      "required_materials": ["entity_index", "character_stage", "event", "source"],
      "optional_materials": ["relationship", "setting", "story_thread"],
      "stop_when": "相关经历阶段的关键选择、变化与转折均有依据；跨阶段缺口已明确。"
    },
    {
      "task_type": "faction_landscape",
      "entry_refs": [
        { "path": "factions/index.json", "record_id": "idx-factions" }
      ],
      "requires_subject": false,
      "required_materials": ["faction_landscape", "entity_index", "faction_stage", "event", "source"],
      "optional_materials": ["relationship", "setting"],
      "stop_when": "目标阶段的主要势力、利益与冲突变化有依据，无法比较的实力不强行排名。"
    },
    {
      "task_type": "worldbuilding",
      "entry_refs": [
        { "path": "navigation/names/index.json", "record_id": "idx-names" },
        { "path": "settings/index.json", "record_id": "idx-settings" }
      ],
      "requires_subject": true,
      "required_materials": ["setting", "source"],
      "optional_materials": ["event", "story_thread"],
      "stop_when": "定义、条件、限制与例外已检查；缺少展示或仅有角色说法时明确说明。"
    },
    {
      "task_type": "relationships",
      "entry_refs": [
        { "path": "navigation/names/index.json", "record_id": "idx-names" },
        { "path": "relationships/index.json", "record_id": "idx-relationships" }
      ],
      "requires_subject": true,
      "required_materials": ["relationship", "event", "source"],
      "optional_materials": ["character_stage", "emotional_stage"],
      "stop_when": "指定双方的关系性质、态度差异和转折有依据，不将单方态度对称化。"
    },
    {
      "task_type": "emotional_arc",
      "entry_refs": [
        { "path": "emotions/index.json", "record_id": "idx-emotions" }
      ],
      "requires_subject": true,
      "required_materials": ["emotional_index", "emotional_stage", "relationship", "event", "source"],
      "optional_materials": ["character_stage"],
      "stop_when": "重要互动、表达、心理与情感转折已有依据，推断与未确认关系已分开。"
    }
  ]
}
```

- `defaults.max_context_tokens` 为正整数，示例值仅是初始建议，不宣称适合所有模型。
- `max_expansion_hops` 为非负整数，限制从直接命中材料继续扩展跨主题关联的深度；目录下钻、证据回读不计关联跳数。
- `evidence_policy` 为 `key_claims` 或 `all_claims`。至少对核心结论保留原文依据。
- `required_materials`、`optional_materials` 使用本文定义的内容 kind，`source` 特指原文。
- required 表示必须尝试取得的材料角色，不要求虚构不存在的文件。一次出场的人物没有阶段传记时，应退回事件和原文，并说明材料简略。
- 数组顺序就是默认读取顺序；`stop_when` 不绕过预算与发布范围。

### 9.2 单次任务输入 `RetrievalTask`

这是未来调用方传入的对象，不要求每次查询都落盘：

```json
{
  "task_id": "task-0001",
  "novel_id": "novel-example",
  "task_type": "biography",
  "subject_queries": ["林舟"],
  "subject_refs": [],
  "focus_ranges": [{ "start": 1, "end": 50 }],
  "mode": "full",
  "max_context_tokens": 12000,
  "task_token_budget": 32000
}
```

| 字段 | 类型 | 规则 |
|---|---|---|
| `task_id`、`novel_id` | string | 任务与小说标识 |
| `task_type` | enum | 上表六类任务之一 |
| `subject_queries` | string[] | 尚未解析的名称、称呼或主题查询 |
| `subject_refs` | Ref[] | 已定位的主体，需确认存在与身份依据 |
| `focus_ranges` | ChapterRange[] | 主要讲述范围；空数组表示已发布范围，不等于全书完整 |
| `mode` | enum(full) | 一期仅允许 full；收到 cutoff 明确返回能力未实现，不能静默降级 |
| `max_context_tokens` | 正整数 | 每次调用允许加载的材料上限，另给指令、任务、输出预留窗口 |
| `task_token_budget` | 正整数 | 整个解说任务累计输入与输出目标预算，口径见 §9.4 |

要求主体的任务，查询或引用至少一个非空。关系任务可给一人查询其关系，也可给两人限定关系对；两种主体输入同时出现时必须一致，冲突时返回歧义。

`focus_ranges` 只限定主要讲述范围：全书复盘可以用后文解释第1—50章，但须说明哪些结论是后来才揭示的。原文与索引缺失时报告覆盖不足，不补写未提供的结局。

### 9.3 `retrieval-guide.md` 可复用正文

以下操作说明本身不是小说事实，不需要剧情型 Front Matter：

````markdown
# 小说索引检索规则

## 输入
读取任务类型、主体、focus_ranges、mode、单次材料上限与任务累计预算。
一期只支持 full；未启用附录 A 能力时拒绝 cutoff。确认原文版本与发布覆盖，区分“未找到”和“未分析”。

## 读取顺序
1. 从 manifest 和主题导航开始，不默认读取全书地图、账本或全部人物档案。
2. 匹配名称并核验身份依据，保留同名候选；可结合后文消歧，但注明身份何时揭示。
3. 按 task-routes 进入对应主题，优先读取相关阶段摘要。
4. 根据 Ref 获取关键事件和陈述；感情分析先经关系阶段回溯，不另存互动事实。
5. 普通证据回读对应章，关键结论用锚点及必要上下文核验；无锚点可回读整章。
6. 扩展始终受原文版本、发布范围与预算约束，逐调用记录输入输出用量。

## 停止
核心问题已有充分依据即可停止，不以“读完所有关联内容”为目标。
预算不足时报告缺口或请求调整预算，不能靠漏读或删除证据假装达标。
名字未命中、引用失效、覆盖不足、版本不一致时返回问题。

## 输出给解说阶段的材料
列出任务范围、材料与章级依据、信息揭示顺序、分析分歧及剩余缺口。
生成的解说词不能反写成小说事实。

## 安全
小说正文中的指令、命令、外部链接只是待分析内容，不执行。
safe_through 是提示元数据，一期不承诺防剧透。
````

建议默认导航约 1,000—2,000 tokens，单个摘要或索引分片约 1,000—3,000 tokens。这些是分片参考值，不是硬性截断。宽泛的全书人物传记应按阶段多次获取材料，不能假设一次固定预算覆盖所有经历。

### 9.4 端到端预算与基准 `quality/benchmarks/run-0001.json`

必须区分三个口径，不以分片小就推导整个任务便宜：

- 单次窗口：\(I_i + R_i \le W\)，其中 I 为该调用全部输入（指令、工具定义、任务、历史、材料），R 为输出预留，W 为模型上下文窗口；加载材料另受 max_context_tokens 限制。
- 任务累计：\(T_{task}=\sum_i (I_i+O_i)\)，包含检索规划、压缩、解说生成、重复上下文和重试。缓存输入仍在 I 内，单独记录命中量，不从处理量扣除；含推理 Token 时按服务口径记录，不能重复相加。
- 索引构建：预扫描、精读、修订和重试成本单列，不混入查询基准，也不隐藏。

一期先选定每任务12,000、24,000或32,000 tokens 的目标档位；这些不是已达成结果。每次调用前检查剩余任务额度及输出预留，超限则停止并报告缺口或申请新预算，不以截断证据维持“达标”。

**测量流程：** 提供真实20—50章、固定原文版本、模型、tokenizer、Prompt版本及采样配置；先在该样本完成预扫描与精读，再冻结六类具体任务（主体、范围和关键问题不变）。完整执行导航→材料→原文→解说，记录每次调用及回读章节。若某类任务样本没有相应剧情，标为不适用并补充样本，不能用空回答计为低成本通过。

```json
{
  "schema_version": "2.0",
  "novel_id": "novel-example",
  "id": "benchmark-run-0001",
  "kind": "benchmark",
  "revision": 1,
  "safe_through": 0,
  "status": "pending",
  "source_version": null,
  "sample_ranges": [],
  "model": null,
  "tokenizer": null,
  "prompt_version": null,
  "sampling_config": null,
  "construction_metrics": null,
  "cases": [
    { "task_type": "chapter_explanation", "task": null, "target_budget": 12000, "metrics": null },
    { "task_type": "biography", "task": null, "target_budget": 32000, "metrics": null },
    { "task_type": "faction_landscape", "task": null, "target_budget": 24000, "metrics": null },
    { "task_type": "worldbuilding", "task": null, "target_budget": 12000, "metrics": null },
    { "task_type": "relationships", "task": null, "target_budget": 24000, "metrics": null },
    { "task_type": "emotional_arc", "task": null, "target_budget": 24000, "metrics": null }
  ]
}
```

- status 为 pending / running / completed；completed 表示测量结束，不等于六类任务全部达标。待测字段是 null，不是0。
- sample_ranges 使用 ChapterRange[]；model、tokenizer、prompt_version 为带版本的字符串；sampling_config 为 `{temperature: number|null, seed: integer|null}`，不支持的参数如实为 null。
- cases[].task 为完整 RetrievalTask 或 null；测量前需固定为具体任务，task_token_budget 等于 target_budget，测完不能追认提高预算。
- construction_metrics 为 null 或 `{prescan: Usage, detailed: Usage, rework: Usage}`；Usage 为 `{input_tokens: integer, output_tokens: integer, calls: integer}`，统计真实非负用量。
- cases[].metrics 为 null 或下表 TaskMetrics。用服务 usage 或匹配模型版本的 tokenizer 测量；服务未提供的数量标 null，并说明 measurement_note，不能把估算写成精确实测。

| TaskMetrics 字段 | 类型 / 含义 |
|---|---|
| `calls` | CallMetric[]，顺序保留每次调用，包括失败重试 |
| `loaded_refs`、`source_refs` | Ref[]、SourceRef[]，记录实际加载材料与回读章节 |
| `input_tokens`、`output_tokens`、`total_tokens` | 非负整数或 null；逐次加总，未知一项则相应总量未知 |
| `peak_context_tokens` | 非负整数或 null，单次输入加实际输出的峰值；不代替调用前的输出预留检查 |
| `elapsed_ms` | 非负整数或 null，端到端耗时 |
| `key_claim_count`、`supported_claim_count` | 非负整数，核心结论数与经原文支持的数量，后者不大于前者 |
| `gaps` | string[]，缺失材料或无法回答的问题 |
| `budget_result` | within / exceeded / unknown / not_applicable |
| `measurement_note` | string 或 null，缺失用量、口径和例外说明 |

CallMetric：`{call_id: string, purpose: retrieval|compression|narration, status: succeeded|failed, input_tokens: integer|null, output_tokens: integer|null, cached_input_tokens: integer|null, elapsed_ms: integer|null}`。缓存命中不得大于输入，重试是新的 call_id；失败且无用量时不能记0冒充精确总量。

同时报告核心结论证据覆盖与 gaps，不接受通过漏读核心问题“证明低 Token”。未提供真实样本和模型配置，本轮六类结果均**待测**。取得结果后回写本节基准；20—50章结果仅适用于样本，还须扩展到跨阶段/全书任务再评估600万字规模。

## 10. 一期视角

一期仅支持全书复盘 `full`，保留信息揭示时间供解说区分“当时表现、角色认知、后来真相与解析推断”；`safe_through` 是提示而非访问控制。若需追更解说，另见附录 A（二期可选、未实现）。

## 11. 生成、分片与一致性检查

### 11.1 两阶段生成与骨架 `navigation/stage-plan.json`

**第一阶段：分块预扫描 → 确认骨架。** 按卷或约20—50章分块扫读完整原文，先记录卷/章节范围、主目标、核心冲突转折、候选人物主列表，再汇总阶段。不是一次给模型加载六百万字，也不把扫读结果直接当成核验事实。

切分优先依据主要目标变化、核心冲突收束、长期场景转换；普通战斗、对话或短暂换场景不独立成阶段。以原书卷界为候选，不强制每卷等于一阶段。确认流程检查全书章节覆盖、相邻边界及理由后，将状态设为 confirmed 并冻结 revision；精读不能自行改边界。

```json
{
  "schema_version": "2.0",
  "novel_id": "novel-example",
  "id": "stage-plan",
  "kind": "stage_plan",
  "revision": 1,
  "safe_through": 1,
  "source_version": "source-v1",
  "status": "draft",
  "scanned_ranges": [{ "start": 1, "end": 1 }],
  "stages": [
    {
      "id": "stage-001",
      "title": "初识与入门",
      "volume_ids": ["vol-001"],
      "chapter_ranges": [{ "start": 1, "end": 1 }],
      "boundary_reason": "示例片段只有初识场景，完整边界待扫读确认。"
    }
  ],
  "character_candidates": [
    { "name": "林舟", "chapter_ranges": [{ "start": 1, "end": 1 }] },
    { "name": "沈岚", "chapter_ranges": [{ "start": 1, "end": 1 }] }
  ]
}
```

- `status`：draft / confirmed；scanned_ranges 为实际扫读覆盖，不预测未提供章节。本例是 draft，不能据此开始真实精读。
- confirmed 时扫描覆盖必须等于目标原文清单，各阶段按全书顺序连续、无重叠地覆盖全部章节；示例只有一章不是全书已扫完。
- `character_candidates` 是候选名称而非权威实体，不预分配正式人物 ID，也不凭扫读强行合并化名。精读时按名称消歧和编号账本确认。
- 人物/势力只为自己相关的规划阶段创建材料，可缺席某阶段；阶段范围可取其参与章节子集。`stage_ref` 指向本文件的阶段 ID，不能仅靠文件名猜归属。
- 精读中关系的小变化记录为同一 stage_ref 下的新快照更新或事件，不能新增规划阶段。快照 ID 稳定且唯一，旧快照不覆盖。
- 重大的边界遗漏登记 coverage_gap，暂停受影响材料发布；显式修订骨架、增加 revision 后，将受影响材料及后续依赖标为 stale 并重建。旧账本依赖不能改数字冒充已重算。

**第二阶段：逐章精读 → 账本应用 → 发布。**

1. 固定原文版本与 confirmed 骨架；建立 prepared 账本，读取所需历史材料。
2. 匹配实体、保留歧义，按 §11.4 预留新增 ID；补读允许，禁止另起编号重复建档。
3. 提取事件、陈述、章级证据，关键结论附锚点；按已确认 stage_ref 归档，主题共享事实。
4. 补齐导航、提取清单及完整写入计划，持久化后进入 extracted。
5. 按 §11.5 applying；业务文件校验完成后先 committed 账本，再 coverage，最后 manifest 的连续发布前缀。

两次扫描的原文遍历量约为 2T，渐近仍为 O(T)；重复上下文、失败重试、补读和骨架修订会增加实际 Token 消耗，必须计入构建基准。扫读可降低提取深度，不等于免费或必然便宜。

### 11.2 何时拆分文件

目标摘要、索引分片初始建议约1,000—3,000 tokens，使用实际模型 tokenizer 测量后调整，不逐条保存估算字段；不能为缩小文件而截断关键事实。

`events/index.json` 固定只列块级入口：target 指向 `events/block-0001.json` 的 `events-block-0001`，kind 为 event_collection。块内 events 数组定义事件；人物等主题已有 Ref 时直接定位块内 ev-*，无需经过根索引。跨章事件扩展后同步块入口的实际关联范围，不重复复制事件。

| 内容 | 拆分方式 | 不应采用的方式 |
|---|---|---|
| 章节导航 | 固定章节范围，例如先按50章分片 | 顶层 index 列全书所有章节正文 |
| 事件集合 | 按章节段或实测大小成组，引用定位到记录 | 一个超大 JSON 混合全书所有事件 |
| 主角经历 | 按经历阶段拆 Markdown | 把六百万字经历塞进一个 profile |
| 名称查找 | 小分片供读取程序精确搜索 | 每次给 LLM 加载全书别名表 |
| 大型设定、关系与故事线 | 拆成同 kind 的记录部分，由中性 IndexFile 导航 | 删除早期更新以缩小当前文件 |
| 覆盖与问题 | 按章节范围分片 | 每处理一章让 LLM 重写全库质量文件 |

单文件的设定、关系或故事线记录拆分时，原路径成为 `IndexFile`，其根 ID 仍为原稳定设定/关系/故事线 ID，充当逻辑锚点。分片使用新的唯一 ID，新增必填 `part_of_ref` 指回锚点，复用原类型的内容字段但只保存本部分的 updates/stages。同一更新或陈述不得在各分片重复定义。此规则不用于替换包含多个事件的集合文件；事件集合按完整事件重新分组，并修复受迁移影响的路径引用。

- `part_of_ref` 是 `setting`、`relationship`、`story_thread` 的可选字段；正常未分片记录不出现。
- 逻辑类型从分片的 kind 或索引条目的目标类型获取，不能要求锚点本身仍是原内容 kind。
- 原实体级 Ref 仍定位到锚点；指向迁移更新或陈述的 Ref 必须批量修正到新分片路径。
- 导航项中的 kind 必须更新为实际目标 `index`，不让消费者猜测目标格式。
- 分片头的原始 label、subjects、introduced_at 等可以重复，必须一致；这些是标识上下文，不代表重复定义全部事实。
- 每份分片继续标注实际揭示时间；一期按版本和发布进度读取，二期启用严格模式时再遵循附录 A。

这是超大记录的扩容规则，不要求初始化时就创建分片锚点。集合级目录过大时优先增加一层普通 IndexFile，无需更改内容模型。

### 11.3 文件生成后的检查清单

| 检查项 | 必须满足 |
|---|---|
| 格式 | JSON 可解析且无重复键；Markdown Front Matter 可解析 |
| 公共头 | schema_version、novel_id、id、kind、revision、safe_through 齐全 |
| 唯一性 | 一个权威 ID 只有一个定义；示例公共子结构不重复导入 |
| 引用 | path 在小说根目录内；目标存在；record_id 可唯一定位；目标类型符合字段要求 |
| 导航 | 新记录至少有一个入口；实体入口与主题根目录无孤立断链 |
| 范围 | 章节号存在，范围合法、升序且不重叠，不凭空预测未来终章 |
| 来源 | 普通陈述定位到章；关键结论锚点可核验；可选版本省略不等于可原位换原文 |
| 证据 | 事实有 Claim 依据；感情定性经 assessment→关系阶段→事实回溯，角色说法不自动升格 |
| 时间 | 提示覆盖实际内容；按 §11.6 抽样核对，发现低估要扩查 |
| 历史 | 新揭示不覆盖旧理解；关系两端态度不自动对称 |
| 覆盖 | 未分析、未发现、缺口和失效区分；有结构不等于已完成提取 |
| 执行 | ID先预留、操作可恢复、账本先提交再发布，异常不得跳过 |
| 阶段 | 骨架已确认且版本匹配，不在精读中静默切分 |
| 预算 | 累计口径包括重复调用与重试；待测不记通过 |
| 二期模式 | 未实现且未经附录 A 验收时拒绝 cutoff |

这些是生成器和后续校验器的验收要求，不代表本轮已经实现校验器。

### 11.4 编号状态 `ledger/id-state.json`

默认同一小说单写者、逐章顺序提交。高水位表示已预留的最大序号，不是已成功建档的数量。

```json
{
  "schema_version": "2.0",
  "novel_id": "novel-example",
  "id": "id-state",
  "kind": "id_state",
  "revision": 1,
  "safe_through": 0,
  "high_watermarks": {
    "char": 0,
    "fac": 0,
    "setting": 0,
    "ev": 0,
    "rel": 0,
    "emo": 0,
    "thread": 0,
    "claim": 0,
    "update": 0,
    "issue": 0
  },
  "pending_reservation": null
}
```

- 高水位键为上述十个固定命名空间，值为非负整数；以最少四位零填充，不限制最大位数。
- `pending_reservation` 为 null 或 `{batch_id: string, ledger_ref: Ref, allocated_ids: string[]}`。同一时刻只有一批未确认预留。
- 原子持久化“递增高水位 + pending_reservation”后，才将该批 ID 复制到章节账本；账本持久化成功后清空 pending_reservation。重启先处理尚未清空的预留，不再次递增。
- 预留后中断可从 pending_reservation 恢复；不再使用的编号也不回收，允许空号。账本按 ID 去重接收批次。
- 已存在的实体先做名称消歧再分配 ID；编号不冲突不能替代实体去重，也不能据同名强行合并。
- 章节 ID 来自原文清单；阶段 ID 来自已冻结骨架；文档、索引及账本 ID 由稳定归属确定。主体内的更新、assessment 等可用“主体 ID + 类型 + 递增序号”，父记录自身的序号也必须在账本固定，重试不重算。示例 `update-setting-0001-001` 属于主体内命名空间，与全局 `update-0001` 不混用。
- 文件锁、原子替换和持久化由执行器负责；启动时先恢复未完成账本，不能在编号预留或章节 applying 期间允许另一个写者进入。

### 11.5 章节账本 `ledger/chapters/ch-000001.json`

这是 prepared 状态模板，不是已成功提取一章的结果。`chapter_ref` 为 `{chapter_id, chapter_order}`，区别于定位结构化记录的 Ref。

```json
{
  "schema_version": "2.0",
  "novel_id": "novel-example",
  "id": "ledger-ch-000001",
  "kind": "chapter_ledger",
  "revision": 1,
  "safe_through": 0,
  "chapter_ref": { "chapter_id": "ch-000001", "chapter_order": 1 },
  "source_version": "source-v1",
  "stage_plan_revision": 1,
  "status": "prepared",
  "allocated_ids": [],
  "input_revisions": [],
  "extraction": null,
  "operations": [],
  "error": null
}
```

| 字段 | 类型与规则 |
|---|---|
| `source_version` | string，与绑定原文版本一致 |
| `stage_plan_revision` | 正整数，提取时采用的 confirmed 骨架版本 |
| `status` | `prepared` / `extracted` / `applying` / `committed` / `blocked` |
| `allocated_ids` | string[]，固定本章新 ID；引用已有 ID 不在此重新分配 |
| `input_revisions` | `{path: string, revision: integer}[]`，记录提取使用的已有索引版本 |
| `extraction` | null 或 `{summary: string, record_ids: string[], coverage_topics: object}`；coverage_topics 使用 §8.2 的八个键与状态 |
| `operations` | WriteOperation[]，保存足够恢复写入的完整目标内容；不依赖 LLM 记忆 |
| `error` | null 或简短错误说明，不包含秘密配置、命令或整章原文 |

`extraction` 是提取清单；完整陈述和材料只在 `operations[].payload` 保存，不另外复制一套提取包。只有提取清单、全部目标载荷及程序计算的指纹完整落盘，才可进入 extracted；空的 prepared 模板不可直接提交。账本保存的载荷是待应用副本，不算新的权威事实定义。

`WriteOperation` 子结构（这是生成中草稿，两个指纹须由执行器补全后才能进入 extracted）：

```json
{
  "operation_id": "ledger-ch-000001-op-001",
  "target_path": "relationships/by-character/char-0001.json",
  "operation": "write_json",
  "merge_key": "target.path+target.record_id",
  "expected_revision": null,
  "expected_sha256": null,
  "result_revision": 1,
  "result_sha256": null,
  "payload": {
    "schema_version": "2.0",
    "novel_id": "novel-example",
    "id": "idx-rel-char-0001",
    "kind": "index",
    "revision": 1,
    "safe_through": 0,
    "title": "关系入口",
    "scope": { "chapter_ranges": [], "subject_refs": [] },
    "coverage_status": "partial",
    "entries": []
  },
  "status": "pending"
}
```

- `operation` 仅允许 `write_json` / `write_markdown`；payload 分别是符合目标模板的完整 JSON 对象或完整 Markdown 字符串，不接受脚本、Shell、任意路径操作。
- `merge_key` 为 string 或 null，说明生成目标载荷时的集合去重依据：有 ID 的记录按 id；IndexEntry 按 target.path+target.record_id；名称匹配按规范化名称、实体与身份状态；非集合为 null。真正写入使用完整目标载荷，不在重试时再次做无条件追加。
- `expected_revision`、`expected_sha256` 对新文件均为 null，要求目标不存在；已有文件则必须分别为旧版本号与程序计算的旧指纹。
- `result_revision` 是正整数，新文件为1，已有文件实际变更时为旧版本+1；无变化不建立写入操作。`result_sha256` 是拟写入字节的指纹，不由模型生成。
- `status` 为 `pending` / `applied` / `failed`。同一章对同一 target_path 最多一条操作；稳定 operation_id 与目标载荷形成对应关系。
- 指纹算法统一 SHA-256。JSON 序列化固定为 UTF-8、两空格缩进、LF、末尾一个 LF，对象键递归按 Unicode 码点顺序排列，数组保持语义顺序；Markdown 统一 LF 与一个末尾 LF。写入时必须使用与指纹计算相同的字节。
- 新记录引用、语义依据及完整覆盖检查针对所有预期目标文件联合进行；有未解释的提取缺口可发布 partial，但不可伪标 complete。

**状态与恢复：**

```text
prepared → extracted → applying → committed
    │          │          │
    └──────────┴──────────┴──→ blocked
```

1. prepared：允许读取或重读当前版本原文；恢复时保留既有 allocated_ids 和提取草稿。
2. extracted：恢复材料齐备；核对输入依赖。首次写入前 input_revisions 不符则停止、重新核对提取依据，不强行覆盖。
3. applying：逐目标比较当前版本和指纹。若匹配预期旧状态则写入；若匹配结果版本与结果指纹，说明该操作已生效，只补记 applied；两者均不符则 blocked。
4. 对“文件写入成功但操作状态未保存”的窗口，以上结果匹配实现幂等。仅 expected_revision 相同不够，不能把碰巧同版本的别的内容当成已成功。
5. 中断后的依赖检查区分本章已应用目标与外部输入：前者允许匹配账本结果，后者仍需匹配 input_revisions。不可把自己刚写出的版本误报为外部冲突，也不可忽略真正的外部修改。
6. 业务操作全部 applied、结构与引用检查通过后，将账本置 committed；随后更新该章 coverage，最后推进 manifest.published_through 的连续前缀。
7. committed 且尚未发布：根据 extraction.coverage_topics 幂等补齐 coverage 和 manifest；不重读、不重复分配编号。已经发布且输入版本未变的账本直接跳过。
8. blocked 不是 committed 后的必经步骤。排除原因后，按可恢复程度回到 prepared、extracted 或 applying。若已有部分操作生效但提取不可恢复，不能直接换一套 ID 重新跑，需先人工核对或显式重建。
9. 原文版本或阶段骨架版本变化属于重建/迁移，不属于普通重试。保留旧账本与 ID 归属，标记受影响覆盖 stale，在隔离的数据版本中复核，不删除历史后假装首次执行。

账本提交不代表发布完成。coverage/manifest 本身也用原子持久化且仅在实际变化时增加 revision；根据 committed 账本重放派生进度可反复执行。

**一致性边界：** 普通文件系统没有跨文件事务。最简执行器在整个章节应用、发布与失败恢复期间暂停该小说检索，重启也必须先恢复再开放；仅筛选 published_through 无法隐藏共享文件的部分改动。编号预留、业务写入、账本状态均需真正持久化（不能只刷新进程内缓存）。这些是待实现与故障注入验收的协议，不是本文已提供的运行能力。

### 11.6 提示元数据抽样审计 `quality/audits/batch-0001.json`

一期检查 safe_through / revealed_at 的准确性，不执行或承诺严格投影。每完成50章或一个阶段，以本批新增、修改的剧情记录为总体，抽查10%（向上取整），至少5条，不足5条全查；同时触发可合并批次。身份揭示、重大反转、明确关系定性等高风险记录另外全查，和随机样本取并集去重。

审计方按章/阶段及记录类型分层抽样，保存实际选择与 revision，避免只抽简单记录。抽样后再打开对应依据与必要后文，反向检查标题、别名、摘要、分析是否依赖比标注更晚的内容，不让生成器自报“无剧透”代替核验。

```json
{
  "schema_version": "2.0",
  "novel_id": "novel-example",
  "id": "audit-batch-0001",
  "kind": "audit",
  "revision": 1,
  "safe_through": 0,
  "status": "pending",
  "source_version": null,
  "chapter_ranges": [],
  "population_count": null,
  "sample": [],
  "findings": []
}
```

- status 为 pending / reviewing / completed；completed 表示整改复核结束，不代表全库绝无错误。
- source_version 在执行时必填；chapter_ranges 是本批范围；population_count 为本批候选记录数，未选样时 null。
- sample 为 `{target: Ref, revision: integer, reason: random|high_risk|expanded}[]`。同一目标只记一次，高风险优先；实际样本数量由数组计算，不重复维护 sample_count。
- findings 为 `{target: Ref, recorded_safe_through: integer, required_safe_through: integer|null, recorded_revealed_at: integer|null, required_revealed_at: integer|null, source_refs: SourceRef[], description: string, status: open|fixed|verified, repaired_revision: integer|null}`。不适用的条目级揭示章为 null；依据不足的 required 值也为 null，不能猜一个数填满。
- 发现低估或误标：登记 issue，扩查相同阶段、别名及引用入口，更新提示与受影响摘要，再由独立复核置 verified。未解决的问题保持 open，不能为了结束批次改成通过。
- 没有抽到不等于不存在；已完成审计保留原抽样 revision，修复用 repaired_revision 记录，不覆盖审计证据。

二期“后文内容 vs 前文投影”的反向隔离测试见附录 A.4，仅在可信读取层实现后执行。本轮记录为 pending，未进行真实小说抽样。

## 12. 虚构样例的引用链与检查结论

### 12.1 示例实例化对照

以下表格把未单独全文展示的文件映射到已有模板，避免后续生成时不知道如何补齐。表内 ID、路径均为示例值：

| 文件 | 套用模板与必要替换 |
|---|---|
| `plot/index.json` | IndexFile，id=idx-plot；entries 指向 doc-arc-001 和章节导航 idx-chapters |
| `plot/arcs/arc-001.md` | Markdown，id=doc-arc-001、kind=arc_summary；引用 ev-0001，不添加样例之外的剧情 |
| `characters/char-0002/index.json` | entity_index，id=char-0002、label=沈岚；引用 ev-0001；如没有独立阶段可 entries=[] |
| `characters/char-0001/stages/stage-001.md` | Markdown，id=doc-char-0001-stage-001、kind=character_stage；引用 claim-0001 与 claim-0004 |
| `factions/fac-0001/index.json` | entity_index，id=fac-0001、entity_type=faction、label=青竹书院；通过 IdentityNote 引用 claim-0003 |
| `factions/fac-0001/stages/stage-001.md` | Markdown，id=doc-fac-0001-stage-001、kind=faction_stage；只记“被沈岚提及”，其余未知 |
| `factions/landscape/stage-001.md` | Markdown，id=doc-landscape-stage-001、kind=faction_landscape；说明仅有一个被提及势力，尚无格局比较依据 |
| `relationships/by-character/char-0001.json` | IndexFile，id=idx-rel-char-0001；entries 指向 rel-0001，scope 限定 char-0001 |
| `emotions/emo-0001/stages/stage-001.md` | Markdown，id=doc-emo-0001-stage-001、kind=emotional_stage；使用 §7.5 分析结构，引用 assessment-emo-0001-001 与 rel-0001-stage-001，source_refs=[] |
| 各主题根索引与分片入口 | IndexFile，目标 ID 使用 §4.2 与 manifest 已声明值；实际新建后再加入父级导航 |

该样例刻意包含“材料不足”的主题，用来验证“不编造以填满模板”，不是声称两段原文足以支持完整势力分析或感情解析。

### 12.2 六类任务的加载链

共同起点为 manifest、catalog 和 task-routes；先检查绑定版本与已发布覆盖。以下是未来实例化后的链路推演，不是当前文件都已存在：

| 任务 | 样例加载顺序 | 停止条件 / 缺口 |
|---|---|---|
| 章节剧情 | `navigation/chapters/block-0001.json` → `plot/chapters/ch-000001.md` → `events/block-0001.json#ev-0001` → `source/vol-001/ch-000001.txt` | 行动和结果可核验，不推断已学会能力 |
| 人物传记 | 名称分片中“林舟” → `characters/char-0001/index.json` → 人物阶段 → 同一事件 → 第1章 | 只能归纳本次经历，不断言稳定性格 |
| 势力格局 | `factions/index.json` → 格局/势力阶段 → claim-0003 → 第1章及关键锚点 | 仅有沈岚自述，组织规模与其他势力未知 |
| 体系设定 | `settings/index.json` → `settings/entries/setting-0001.json` → claim-0002 → 第1章及静心说法锚点 | 无实际展示、上限或代价证据 |
| 人物关系 | 人物入口 → `relationships/by-character/char-0001.json` → rel-0001-stage-001 → 事件陈述 → 第1章 | 只确认表达与互动，不认定正式师徒 |
| 感情线 | `emotions/index.json` → assessment-emo-0001-001 → relationship_links → rel-0001-stage-001 → 同一事件 → 第1章 | 保持 uncertain，分析摘要不复制互动 |

直接按 Ref 命中块内事件可跳过 events/index.json；尚无 Ref 时，事件根索引先查块，再查块内 ID，两种路径不混淆层级。

这里的 `文件#ID` 仅用于表格展示；实际 Ref 仍严格拆成 `path` 和 `record_id` 两个字段。

六类入口复用同一个 `ev-0001` 及四条陈述，不创建“人物版事件”“势力版事件”“感情版事件”。按 ID 加载集合中的目标记录，不等于把整份事件分片传给模型。

### 12.3 恢复与内容边界的预期行为

以下为协议推演与未来故障注入用例，未对真实执行器运行：

| 情形 | 预期行为 |
|---|---|
| 高水位已增加，章节账本未收到 ID | 从 pending_reservation 恢复同批 ID，不重新递增或回收 |
| 重试已经 committed 的章节 | 版本相同则跳过提取，仅补未完成发布 |
| 文件已写成功，操作仍为 pending | 校验结果版本与结果指纹匹配后补记 applied，不重复追加 |
| 目标版本匹配但内容指纹不同 | blocked，不能仅靠 revision 判成功 |
| 某个依赖被外部修改 | 停止并重新核对；自己已应用的目标按账本结果区别处理 |
| applying 中断但完整载荷仍在 | 恢复未完成操作，暂停检索直至发布完成 |
| prepared 无完整提取 | 允许回读同版本原文，保留已分配编号 |
| 账本 committed 后 coverage/manifest 发布失败 | 重放派生进度，不重新解析，不能越过未提交章节 |
| 原文或骨架版本变化 | 标 stale，显式迁移/重建，不按普通重试直接跳过 |
| 普通证据只有章级位置 | 可回读整章；关键结论无可靠锚点时报告待补证据 |
| 同名、感情未确认或多方感情线 | 不强行合并身份或认定爱情；多方分析引用全部相关关系阶段 |
| 预算预计超限 | 停止或调整预算，保留已知缺口，不能削去核心证据假装完成 |
| 第80章回忆很久以前的事 | 故事时间与呈现位置分开，revealed_at 不早于80 |
| 一期收到 cutoff | 拒绝未实现能力；隔离用例仅在附录 A 执行 |
| 只发布了前50章却要求全书传记 | 报告覆盖限制，不把未处理的后续当作人物结局 |

### 12.4 本轮验证范围

本轮对模板执行 JSON 语法解析、公共文件头检查、六类任务路由检查，以及 Markdown Front Matter 解析；另按虚构原文核对示例引用和上述安全边界。

本轮没有创建真实小说数据集，因此没有验证全库物理引用存在性、600万字运行性能或严格模式端到端隔离。字段语义检查也不能替代后续真实小说的提取质量评估。

**生成时的最小原则：先使用统一模板记录可证实的信息，再按任务加载关联材料和原文；不要为了目录完整而预写未经证实的内容。**

## 附录 A：严格截止章节（二期可选、未实现）

本附录不属于一期默认流程，不能因为存在时间字段就宣称支持严格模式。启用前必须实现可信读取层，完成元数据审计及下述隔离验收；一期接到 cutoff 必须拒绝而不是降级成 full。

### A.1 启用契约

二期扩展 RetrievalTask：允许 `mode=cutoff`，增加必填正整数 `knowledge_cutoff=N`；focus_ranges 超过 N 返回参数冲突。full 模式不携带该字段。读取层先完成筛选，再将结果交给独立解说上下文，不能让同一个 LLM 读完后文再删除。

阶段计划、编号状态、章节账本、基准与审计记录仅供执行器使用，不向 cutoff 解说上下文返回。全书预扫描本身可能包含结局，不能复用预扫描或 full 模式的对话历史。

### A.2 读取前投影

| 内容 | 必须验证与筛选 |
|---|---|
| 文件整体 | 审计确认 safe_through ≤ N 才可整份返回；否则只返回以下有明确定义的投影，不支持的类型拒绝 |
| IndexFile | 保留 entry.safe_through ≤ N 的项；重建 scope、去除全库数量；根 title 必须中性，否则拒绝 |
| name_lookup | matches 按 revealed_at 筛选；无可见匹配的名称组整体删除，不能提前暴露 normalized_name |
| source_chapters / SourceRef | 清单章节号、safe_through 不超过 N；章级引用继承绑定版本，若有锚点或 locator 同样核验，不因其可选而放松章节边界 |
| event_collection | introduced_at ≤ N，只返回 revealed_at ≤ N 的完整 updates；无可见更新则删除事件 |
| entity_index / setting | introduced_at ≤ N；根 label/category 必须是首次出现时信息，无法保证则拒绝；身份与设定更新、关联链接按 revealed_at，entries 按 safe_through 筛选 |
| relationship | introduced_at ≤ N；stages 同时满足 revealed_at、as_of ≤ N；subjects 只用当时的实体对应 |
| emotional_index | 根名称不含未来结论；参与者、assessments、relationship_links 按 revealed_at，entries 按 safe_through 筛选；评估引用的具体关系阶段必须可见，不能只保留定性 |
| story_thread | introduced_at ≤ N；更新按 revealed_at 筛选，状态与分类由可见更新推导，根名称不得泄露答案 |
| issues / coverage | 问题只显示 opened_at ≤ N 的记录和可见更新；coverage 仅返回任务范围内且不超过 N 的部分 |
| Markdown | safe_through 或 as_of 超过 N 均不整份返回，不以自动删句冒充历史材料；感情摘要中的 assessment 和关系阶段也须可见 |

- 裁剪单位是带时间的完整更新，不能把未来结论藏进早期更新的摘要或引用。单独按 ID 读取陈述也要校验所属更新，避免绕过父层边界。
- 名称、身份对应、根字段及所有 Ref 均检查依据。原子项依赖未来记录时拒绝该项并登记问题；仅记录内容安全而目标未来时不能盲目跟随链接。
- 从投影去掉隐藏项数量、未来错误细节和源文件最大揭示章等旁路。结果是临时视图，不改写原始记录或虚抬 as_of。
- 分片锚点与内容分片均需校验，未知类型默认拒绝。普通源文件搜索、日志和错误信息不得绕过读取层。

### A.3 阶段与上下文回退

阶段为第1—100章、查询 N=60 时，不读取阶段末总结；使用已确认安全的旧摘要和截至60章的章节、事件及原文补齐。未预存安全摘要不等于可以读完全部再要求模型忘记。

启用前需检查基础章节摘要是否含后文解释；不符合的摘要须重建或排除。缓存至少按小说、原文版本、依赖 revision、模式、截止章、目标与范围区分，full 缓存不能直接给 cutoff。

以上控制仅针对任务提供的材料，无法抹除模型预训练中的已知剧情，亦无法消除用户主动在任务中提供的剧透；输出只能采用当前材料支持的判断。

### A.4 反向审计与启用门槛

在 §11.6 的抽样之外，对身份揭示、重大反转、明确关系定性全部测试：由独立审计方读取后文，登记禁止提前出现的姓名对应、答案和结论；用新的解说上下文分别测试“揭示前一章、揭示章、阶段中点”，保存返回路径、字段和结论，检查是否提前出现禁项，并检查应可见的材料是否被错误隐藏。

| 用例 | 预期 |
|---|---|
| 第120章才确认身份，N=119 / N=120 | 前者不能经别名或关系合并泄露；后者才允许使用确认依据 |
| 实体 introduced_at=100，N=50 | 不返回根姓名或空壳记录 |
| 第90章新增感情线参与者，N=60 | 不经名称、参与者、assessment或摘要泄露第三人 |
| 事件跨第1—3章，N=2 | 不返回第3章结果 |
| 阶段1—100章，N=60 | 不能通过阶段末摘要泄露后文 |

必须实现读取权限隔离，完成上述测试且解决已发现泄露后才可启用。发现泄露立即禁用相关投影并扩查依赖；抽样通过不是全库永不泄露的证明。本轮仅定义方法，未运行投影测试。
