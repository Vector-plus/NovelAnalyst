# Narration（解说词生成）模块决策记录

## 设计原则
- 对应设计文档《03-核心图设计_解说词生成.md》v2.0：1 个 ReAct Agent + 1 个 SKILL.md + ~7 个只读工具，无 StateGraph、无多 Agent、无 checkpoint。
- 解说词是「秒~分钟级、无状态、纯只读」的 RAG 任务，不需要状态机。

## 关键决策
1. **复用原语、不复用大而全装配**：`build_narration_agent` 复用 `create_agent` + `create_chat_model` + `load_skills`，不复用 `build_agent`（不需要 middleware/memory/sandbox/checkpointer）。
2. **SKILL.md 全文即身份**：`system_prompt` 直接注入 `novel-narration-generator` SKILL.md 正文，不走渐进加载（唯一必用 skill）。
3. **task_type 以 SKILL.md 为准（五类）**：`chapter_explanation`/`biography`/`faction_landscape`/`worldbuilding`/`emotional_arc`。skill 可调整，`generate_narration._TASK_TYPES` 跟随调整。
4. **使用 novel_id + InjectedState 代码注入（不交给 LLM）**：一本小说的**索引树根目录**（index root）为 `config.workspace_path / novel_id / novel`（如 `.deerflow_simple/workspace/asdafd454da6df/novel/`，注意比 space root 多一层 `novel/`）。`generate_narration` 的 `novel_id` 参数用 `Annotated[str | None, InjectedState("novel_id")]` 标注，**不出现在 LLM 可见的 tool schema 中**，由代码从 graph state 注入：用户在创建对话时通过 `client.chat(..., novel_id=xxx)` 传入 → `submit_run(novel_id)` → graph 输入 payload → `InjectedState` 注入工具。工具内部 `resolve_novel_root` 完成 id→**索引树根**路径的**确定性映射**（复用 `resolve_novel_index_path`，含防路径穿越 + 目录存在性校验）。彻底消除 LLM 幻觉/猜测 novel_id 的风险。
5. **参数合法性短路**：task_type 枚举 / 必填矩阵在 `generate_narration` 入口用纯 if/else 校验，不花 token。
6. **只读契约**：ReadOnlyFs 只提供 read_file/ls/exists，无写方法；工具集绝不含 write_file/bash。
7. **skill references 按需加载（关键）**：`load_skills` 只解析 SKILL.md frontmatter + 正文，**不加载 references/ 目录下的任何文件**（`Skill` 类型也没有该字段）。但 SKILL.md 正文引用了大量方法论文档（retrieval-playbook / style-guide-* / structure-templates / evidence-and-boundary / examples），这些文件**不在 novel_root 内**，无法用锚定 novel_root 的 `read_file` 读取。因此新增两个锚定 skill 目录（`skill.path` 的 parent）的只读工具：
   - `read_skill_reference(path)`：读 references/、examples/ 下任意文件。
   - `list_skill_references(path="references")`：递归列出 skill 资源目录下的所有文件，让 LLM 先摸清 references/ 里到底有哪些风格/检索指南可用，再决定读哪个。
   
   二者配合，实现「不同类型解说任务风格与检索方式不同」的按需加载，而非一次性全量注入。

## 三条确定性护栏（不交给 LLM）
1. **名字消歧**：`search_name` 三层（NFKC 精确 → difflib 模糊 → LLM 语义召回）；存在性由代码裁决，LLM 只「挑」不「裁决」。
2. **覆盖预检**：`load_manifest` 返回 published_through / coverage 状态。
3. **路径穿越防护**：ReadOnlyFs 解析后的路径必须位于 novel_root 内。

## 预算守护（token 上限 + 工具调用次数，硬约束）

背景：`create_agent` 在 langchain 1.x 已移除 `max_iterations` 参数，agent 在「模型不再调用工具」时
自然终止，唯一的硬限制是 `recursion_limit`（LangGraph super-step 递归上限，默认 9999，非迭代次数）。
SKILL.md 的 `task_token_budget` 只是给 LLM 的软约束（stop_when 提示），LLM 可能不遵守，
存在 ReAct 死循环 / token 失控风险。

方案：预算守护已抽成 `stream.py::BudgetGuard`（可复用），lead_agent 与 NarrationAgent 共用。
在 `generate_narration` 的 `astream(stream_mode="messages")` 消费循环里，用 `BudgetGuard` 做两个硬约束：

1. **工具调用次数**：统计 `tool_result` 事件数（一次完整工具往返算一次），达到
   `config.narration_max_tool_calls` 即中断流。
2. **token 预算**：用 `estimate_tokens`（中文 1 字≈1 token，英文 4 字符≈1 token）累计
   「循环增量」token（模型输出 + 工具参数 + 工具返回），达到 `config.narration_token_budget`
   即中断流。

任一超限：`guard.check()` 返回 True → `break` 中断流，返回结果带 `budget_truncated=True`；
若此时还没写出正文，返回 `status=error`（明确报错），否则返回 `status=ok` + 不完整 draft
（诚实标注被截断）。

**注意**：`narration_max_tool_calls` / `narration_token_budget` 只约束内层 NarrationAgent。
lead_agent 层的预算由 `config.agent_max_tool_calls` / `agent_token_budget` 约束（见根 AGENT.md）。

估算误差说明：token 估算有少量误差（未用 tiktoken），但作为「防失控」的硬约束足够；
需要精确计费时，可在 middleware 层用模型返回的 usage_metadata 补充。

## 解说词结果落盘（result 目录）

- **落盘位置**：`config.workspace_path / novel_id / result`（space root 下的 `result/`），
  路径解析唯一来源是 `spaces/paths.py::resolve_novel_result_path`（复用 `resolve_novel_path` 防路径穿越）。
- **语义区分（关键）**：`result` 是解说词的**产出物写入区**，挂在 **space root** 下；
  而 `novel`（index root）是索引的**只读消费区**。二者语义不同、不可混用——narration 检索工具
  仍只读 index root，落盘只发生在 `generate_narration` 工具入口（不是 NarrationAgent 的检索工具），
  因此不违反「只读契约」。
- **落盘时机**：仅在 `status=ok`（含 `budget_truncated` 的部分成功）且 draft 非空时落盘；
  `ambiguity`（含 `[CLARIFICATION_NEEDED]`）与 `error` 一律不落盘。
- **文件名**：`{task_type}_{yyyyMMdd_HHMMSS}_{slug}.md`，slug 为 subject（优先）或
  focus_ranges 或 `all`，经 `_sanitize_filename` 清洗（去路径分隔符/空白、保留中文、截断 50 字符）。
- **开关**：`config.narration_save_result`（默认 True）。关闭后不落盘。
- **容错**：落盘失败不阻断主流程（解说结果仍正常返回），仅在返回 dict 里附 `save_error`；
  成功时返回 dict 附 `saved_path`（文件绝对路径字符串），供 lead_agent 告知用户保存位置。

## 文件职责
| 文件 | 职责 |
|---|---|
| `read_only.py` | ReadOnlyFs 只读文件访问器（地基，含 is_dir） |
| `names.py` | search_name 第 1、2 层（NFKC + difflib） |
| `tools.py` | 7 个业务只读工具 + read_file/ls + read_skill_reference/list_skill_references + RESOLVE_NAME_SYSTEM 常量 |
| `agent.py` | build_narration_agent 极简装配（挂载 read_skill_reference + list_skill_references） |
| `generate_narration.py` | generate_narration 工具入口（含参数校验、流式透传、预算守护、结果落盘到 result/） |

## 测试
- 测试用例：`examples/10_narration.py`（用设计文档 §12 虚构样例动态构造最小索引树）。
- 确定性工具链测试（不调 LLM）：`python examples/10_narration.py`，逐项验证 7 个只读工具的检索能力。
- 端到端检索测试（调 LLM）：`python examples/10_narration.py --e2e`，让 NarrationAgent 自主走一遍「名字消歧 → 下钻检索 → 原文核验」。
- SimpleClient 端到端测试（调 LLM）：`python examples/11_narration_client.py`，走完整链路
  `SimpleClient(lead_agent) → generate_narration 工具 → resolve_novel_root → NarrationAgent`。
  它把 fixture 写到 `workspace/{novel_id}/novel`（index root）下；`novel_id` 由代码通过
  `client.chat(..., novel_id=xxx)` 注入（prompt 不含 novel_id），验证 InjectedState 链路。
- 名字索引补齐（数据工具，方案A）：`python examples/12_backfill_names.py [novel_root]`，从
  `characters/index.json` 生成 `navigation/names/part-0001.json`，补齐 `search_name` 依赖的
  名字分片（见「真实数据验证结论」）。

## 已知待办
- `load_entity` 目前按 entity_ref.path 定位 + 读 stages/*.md；跨主题实体（faction_stage 等）的完整加载待 M2 补充。
- **novel_id 会话绑定（已解决）**：`generate_narration` 的 `novel_id` 现由代码通过
  `InjectedState("novel_id")` 从 graph state 注入，用户在创建对话时经 `client.chat(..., novel_id=xxx)`
  传入，prompt 不含 novel_id、LLM 不可见，彻底消除幻觉风险。
- **流式透传（已解决）**：`generate_narration` 已从同步 `invoke` 改为 async + `astream(stream_mode="messages")`，
  内层事件通过 `emit_event` 透传回 lead_agent 事件通道（见根 AGENT.md「流式执行记录可见性」）。
- **预算守护（已解决）**：新增 `config.narration_max_tool_calls`（工具调用次数上限，默认 40）与
  `config.narration_token_budget`（token 预算上限，默认 32000），在 `generate_narration` 的消费循环里
  用纯代码硬约束，任一超限即中断流，不再依赖 SKILL.md 的 stop_when 软约束（详见下文「预算守护」）。

## 真实数据验证结论（名字索引是硬前置依赖，方案A已补齐）

用真实 wukong 索引（`workspace/55fa54e9abf04ed88da8b3abf9ba3993/novel`）验证：

- **名字索引（`navigation/names/`）是解说任务的硬前置依赖**。SKILL.md 主流程要求
  `biography`/`worldbuilding`/`emotional_arc` 等带 `subject` 名称的任务，必须先经
  `navigation/names/index.json` → `part-*.json` 做精确匹配（`search_name`）。
- **根因**：`characters/index.json`（实体索引）与 `navigation/names/`（名字查找表）是两套
  数据。前者存实体详情（`title` 是主名），后者存所有实际出现名字 surface→entity_ref 映射。
  novel-index-creator 的骨架脚本 `init_skeleton.py` 生成 `names/index.json` 时 `shard_refs: []`
  是初始值，而精读工作流没有显式的「生成名字分片」步骤，导致 wukong 索引生产时漏掉这一步。
- **方案A（已实施）**：新增 `examples/12_backfill_names.py`，从 `characters/index.json` 的
  `title` 字段生成 `navigation/names/part-0001.json`（MVP，只覆盖主名 `name_type=name`，
  `basis_refs` 用实体 index 占位、`source_refs` 留空），并更新 `names/index.json` 的 `shard_refs`。
  生成 170 个名字后，`search_name("唐僧"/"孙悟空"/"沙僧"/"猪八戒")` 均返回 `unique`，
  `load_entity("char-0001")` 也能按 record_id 反查 path 定位。
- **待办（方案B，流程根治）**：novel-index-creator 精读工作流应显式增加「生成名字分片」步骤，
  否则每个新小说都会漏。此外 MVP 只覆盖主名，别名/化名/称号（`name_type=alias/title/...`）与
  真实原文锚点（`source_refs`）仍需精读工作流补全。
