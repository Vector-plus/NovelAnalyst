# 检索指南 Retrieval Playbook

本指南是 LLM 在**不加载全书原文**的前提下，从索引目录中找到所需材料的"路径图"。所有五类解说任务都必须按本指南加载材料，严禁跳过入口直接搜索内容。

---

## 零、全局原则

### 0.1 共同起点（五类任务都必走）

```
novel/manifest.json
   ├─ 读取 source_version / published_through / index_version
   └─ 定位各入口 Ref（navigation / plot / characters / factions / settings / events / relationships / emotions / threads / quality）

novel/navigation/catalog.json         # 全局分片目录
novel/navigation/task-routes.json     # 五类 task_type 的推荐入口路由

↓ 如 subject 为名称字符串
novel/navigation/names/index.json     # 名称首字母 → 分片
novel/navigation/names/part-*.json    # 精确匹配 name/alias → entity_ref
```

**三条铁律**：

1. **先读 manifest 再读其他**：所有后续加载都要校验 `index_version` 与 `source_version`，版本不符要在元信息中标注。
2. **名称解析必须精确**：命中 ≥ 2 个候选时**保留全部**返回"歧义待消解"，不要凭语境猜测。
3. **只读消费端**：Skill 全程不写回任何索引文件，不要调用任何写接口 / `coverage.json` 更新操作。

### 0.2 预算与停止

- **默认 `task_token_budget = 32000 tokens`**。累计加载量达到 90% 时**停止扩展加载**。
- 停止扩展后若核心结论仍缺证据，优先**牺牲"文采修饰"**而非"证据保留"：宁可输出 1200 字的紧凑稿，不要输出 1500 字但有未核验结论的稿。
- 被预算截断的章节/材料必须在 `meta.coverage_gaps` 中说明；`meta.budget_truncated=true`。

### 0.3 揭示顺序与 anchor 回读

- 加载任何结构化记录（Event / Claim / Stage / Relationship / Assessment）时都要注意：
  - `revealed_at`：这条信息在哪一章对读者揭示；
  - `safe_through`：所在文件保证不包含晚于该章的"未来剧透"。
- **一期固定 `mode=full`**。即便 `revealed_at` 晚于 `focus_ranges.to`，也可以用于叙述，但**必须用"后来才揭示"口吻**，不得把未来结论当作当前章节的既成事实。
- 关键结论型 Claim（身份揭示、重大反转、关系定性、能力规则）必须按 `SourceRef.anchor` 回读原文 `source/vol-*/ch-*.txt`：
  - **anchor 存在**：读取 `anchor.start_line` ~ `anchor.end_line` 对应段落核验；
  - **anchor 缺失**：扩读整章，并在稿件尾部标注"证据有限（无锚点）"。

### 0.4 覆盖状态处理

查询 `novel/quality/coverage.json` 中目标范围的 `coverage.topics[task_type]`：

| 状态 | 处理 |
|---|---|
| `complete` | 正常使用结构化索引 |
| `partial` | 使用现有索引 + **退回原文**兜底，并在 `meta.coverage_gaps` 标注 |
| `stale` | 等同 `partial`，但更倾向于以原文为准 |
| `not_analyzed` | **直接拒绝生成**，返回"该范围尚未索引"（见边界矩阵） |

---

## 一、章节剧情解说（`chapter_explanation`）

### 入口 → 必读 → 可选 → 停止条件

**入口**：
```
navigation/catalog.json  →  navigation/task-routes.json["chapter_explanation"]
```

**必读**（按顺序）：

1. `navigation/chapters/block-*.json` —— 定位 `focus_ranges` 覆盖的章节块
2. `plot/chapters/ch-*.md` —— 目标范围内每一章的逐章摘要
3. `events/block-*.json` —— 范围内的 `ev-*`（关键事件、冲突、转折）；重点关注 `category=turning` 或 `impact.scope ≥ arc` 的事件
4. `source/vol-*/ch-*.txt` —— **按 anchor 回读**原文片段（至少覆盖所有"关键结论型 Claim"）

**可选**（按需）：

- `plot/arcs/arc-*.md`：当 `focus_ranges` 的首章 `arc_ref` 与结构化叙事相关时读入，获得阶段级上下文
- `entity_index`（人物/势力简表）：避免对出场人物身份理解有误（例如"后来才揭示的真身"）
- `settings/entries/setting-*.json`：当章节出现能力/规则展示，用于准确描述"施展了什么"
- `threads/thread-*.json`：当章节出现伏笔/线索收束时，用于解说点评段的呼应

**停止条件**（满足任一则停止扩展加载）：

- 目标章节范围内的所有**主要行动、转折、结果**均已有对应 `ev-*` 或原文依据；
- 已覆盖 `focus_ranges` 内的全部"关键结论型 Claim"（有 anchor 的全部回读完毕）；
- 累计 token 达预算 90%。

---

## 二、人物传记解说（`biography`）

### 入口 → 必读 → 可选 → 停止条件

**入口**：
```
navigation/names/* → 得到 subject 的 char-* Ref
characters/char-*/index.json
```

**必读**（按顺序）：

1. `characters/char-*/index.json` —— 人物入口，获取 `stages`、`identity_links`、`core_claims`
2. `characters/char-*/stages/stage-*.md` —— **覆盖 `focus_ranges`（若无 `focus_ranges` 则全部）**的人物阶段文稿
3. 阶段文稿中引用的 `ev-*`（在 `events/block-*.json` 中读取）与 `claim-*`
4. 关键结论型 Claim 的原文 anchor 回读（身份揭示、能力突破、重大选择、关系定性）

**可选**：

- `relationships/by-character/char-*.json`：关系副线补充动机（例如"他的叛变是否与某段关系相关"）
- `settings/entries/setting-*.json`：能力成长线索（当传记需要讲"他如何修炼到这一步"）
- `threads/thread-*.json`：人物贯穿的故事线（命运式伏笔）
- `emotions/emo-*/index.json`：若 extra_hint 涉及情感，可引入

**停止条件**：

- 所有涉及的阶段均有依据，无"空白阶段"进入稿件；
- 跨阶段身份变化（`identity_links`）已核对，不混用新旧身份；
- 累计 token 达预算 90%。

---

## 三、势力格局解说（`faction_landscape`）

### 入口 → 必读 → 可选 → 停止条件

**入口**：
```
factions/index.json
   ├─ 不填 subject → factions/landscape/stage-*.md（取与 focus_ranges 对应的格局快照）
   └─ 填 subject   → 名称解析得 fac-* → factions/fac-*/index.json
```

**必读**（按顺序）：

1. `factions/index.json` —— 势力总表
2. `factions/landscape/stage-*.md` —— **格局快照**（本阶段台面有几方势力、各自定位）
3. 涉及势力的 `factions/fac-*/index.json` 与 `factions/fac-*/stages/stage-*.md`
4. 关键 `ev-*`（势力间冲突、合作、翻盘事件）与 `claim-*`（势力性质、利益归属、隐藏矛盾）
5. 必要原文回读（对"隐藏矛盾""真正后台"这类结论型 Claim）

**可选**：

- `relationships/pairs/rel-*.json`：高层人物之间的互动（势力博弈的具体执行层）
- 关键执行者的 `characters/char-*/stages/stage-*.md`（关键 NPC 的动机）
- `threads/thread-*.json`：阴谋线、伏笔线
- `emotions/emo-*`（通常跳过，除非 extra_hint 涉及"情感绑定导致势力转向"）

**停止条件**：

- 目标阶段的**主要势力、利益、冲突变化**均有依据；
- 若缺乏比较依据，**不强行排名**（例如避免写"XX 势力是本阶段最强"除非 claim 明确）；
- 累计 token 达预算 90%。

---

## 四、体系设定解说（`worldbuilding`）

### 入口 → 必读 → 可选 → 停止条件

**入口**：
```
settings/index.json
   └─ 名称解析得 setting-* → settings/entries/setting-*.json
```

**必读**（按顺序）：

1. `settings/index.json` —— 设定总表（获取层级/分类）
2. `settings/entries/setting-*.json` —— **主体设定条目**：定义、条件、代价、限制、例外、`certainty` 字段（explicit / reported / inferred）
3. 该设定 `related_event_refs` 与 `demonstration_event_refs` 指向的 `ev-*`
4. 关键展示章节的原文回读（**anchor 优先**；无 anchor 则读 ev 关联的整章）

**可选**：

- `settings/entries/*.json` 中通过 `links` 关联的相邻设定（上下级、相邻、对立体系）—— 用于结尾的"体系对比"段
- 关键使用者的 `characters/char-*/stages/stage-*.md` —— 用于"典型展示"段
- `threads/thread-*.json` —— 体系背后的世界观伏笔

**停止条件**：

- **定义、条件、代价、限制、例外** 五要素全部检查完毕；
- 对每一项标明 `certainty`：**`reported`（角色说法）不得升格为 `explicit`（原文展示）**；
- 原文无实际展示的，必须标注"目前仅为角色说法"；
- 累计 token 达预算 90%。

---

## 五、感情线解析（`emotional_arc`）

### 入口 → 必读 → 可选 → 停止条件

**入口**：
```
navigation/names/* → 得到双方 char-* Ref
emotions/emo-*/index.json          # 若 subject 是感情线 Ref 或可解析为已有感情线
   └─ 若无 emo-*，则退回 relationships/pairs/rel-*.json
```

**必读**（按顺序）：

1. `emotions/emo-*/index.json` —— 感情入口，获取 assessment 列表与 turning_event_refs
2. assessment 引用的 `relationships/pairs/rel-*.json` 的 `rel-*-stage-*`（关系阶段快照）
3. `turning_event_refs` 的 `ev-*` 与 `claim-*`（情感转折事件）
4. 关键原文回读（**所有 `assessment.category=explicit` 的锚点必读**；`uncertain` 的锚点读 1-2 处作旁证）

**可选**：

- `emotions/emo-*/stages/stage-*.md` —— 已有的分析文稿（可以引用但不要完全照搬）
- 双方 `characters/char-*/stages/stage-*.md` —— 侧写两人在该阶段的性格与处境
- `threads/thread-*.json` —— 感情伏笔线
- `factions/`（通常跳过，除非 extra_hint 涉及"门派立场影响感情"）

**停止条件**：

- 重要互动、表达、心理与情感转折均有依据；
- **推断（inferred / uncertain）与事实（explicit）已分离**，不把保护推理成爱情；
- 多方感情线中所有相关主体均覆盖；
- 累计 token 达预算 90%。

---

## 附：加载决策速查卡

| 场景 | 该读 | 不该读 |
|---|---|---|
| 用户只给了人物名 | `names/*` 精确匹配 | 全局搜索原文 |
| 名称命中多个候选 | 返回歧义列表 | 擅自选最热门的 |
| 结论型 Claim 有 anchor | 读 anchor 对应原文片段 | 跳过回读 |
| 结论型 Claim 无 anchor | 扩读整章 + 标注"证据有限" | 省略并假装有依据 |
| `coverage=not_analyzed` | 返回"该范围尚未索引" | 用其他主题的索引硬凑 |
| `coverage=partial`/`stale` | 补读原文 + `coverage_gaps` 标注 | 不加标注直接出稿 |
| `claim` 存在 `supersedes_refs` | 优先采用较新 revision | 混用新旧结论 |
| `revealed_at > focus_ranges.to` | 用"后来才揭示"口吻 | 当作主角当时的已知 |
| 累计 token 达预算 90% | 停止扩展 + `budget_truncated=true` | 悄悄截断证据 |
| 收到 `mode=cutoff` | 直接报错 | 假装支持 |
