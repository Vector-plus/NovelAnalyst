# index_builder 模块设计说明

## 定位

索引生成工作流（解析工作流）的 graph + 节点 + Agent。对应设计文档
《03-核心图设计_索引生成.md》，但按 P0+P1 最短链路裁剪。

## 一期范围（P0+P1）

```
skeleton（零 LLM，确定性）
  → prescan（fan-out 扫卷 + fan-in 合并，有 LLM）
  → review_plan（Human-in-Loop interrupt）
```

deepread / audit / review_issues（Human-in-Loop）已接入（P2 / P3）；derive（向量索引）
按决策推迟，一期不做。

## 对设计文档的纠正（不盲从）

### C1 · StagePlanMergeAgent 不写文件

《04-prompt_第一阶段粗读.md》§3.2 原让 Agent 用 `write_file` 直接落盘
stage-plan.json，但这与《03-核心图设计》§5.10「写入全走确定性路径，ReAct 只给
只读工具」冲突。**按后者为准**：Agent 只产出结构化 JSON，由 prescan 节点解析后
确定性落盘（并强制修正 novel_id / source_version / status=draft），杜绝 LLM
幻觉乱写。

### C2 · 脚本逻辑迁移而非 subprocess

`design/doc/scripts/` 的 4 个脚本（chunk/init_skeleton/shard/validate）是 CLI
（argparse + sys.argv + 硬编码路径），不能 subprocess 复用。已把 `main()` 函数体
改写为包内纯函数（`_chunk_novel` / `_init_skeleton` / `_shard_chapters` /
`_validate_index`），签名从 sys.argv 改为显式参数，路径由 state 传入。脚本文件
本身保留作为 CLI 调试入口（不在本模块内）。

### C3 · build_novel_index 的「异步执行」不阻塞 lead_agent

设计文档 §6 的 `build_novel_index` 立即返回 task_id 是对的，但「异步执行」没有
落地载体。本模块的 graph 由 tasks 模块（TaskManager）驱动执行，`novel_id` 由代码
注入（`build_initial_state` 经 `resolve_novel_index_path` 确定性映射 index root），
不交给 LLM 决策。

## 关键决策

### D1 · 星型路由

`START → entry → route → {skeleton|prescan|review_plan} → entry → ...`，`phase`
字段即状态机。任何中断后恢复都走统一 entry 入口。`route` 对未知 phase（deepread/
done）落到 END。

### D2 · interrupt_before=["review_plan"]

graph 在 review_plan 前中断，`graph.get_state(config).next` 非空表示 paused。
resume 时 `update_state({"pending_human_decision": decision})` 后从 checkpoint 继续。

### D3 · prescan 幂等一期不做

一期不做 `_staging/prescan/vol-xxx.done` 幂等标记（最短链路优先）。checkpoint
恢复会从 prescan 节点重入并重扫；幂等优化二期补。skeleton 零 LLM、秒级，重跑无害。

### D4 · Agent 按 novel_root 缓存

ScanVolReActAgent / StagePlanMergeAgent 按 novel_root 缓存（对齐 narration 的
`_agent_cache` 模式），工具锚定 index root，不同小说复用编译好的 graph。

### D5 · 三层去重（deepread 幂等底线）

对齐 03 文档 §4.7「按章幂等（record 级）」+ templates §11.5 四态 + §11.4 编号。
去重分三层，粒度由粗到细、缺一不可：

| 层 | 判重依据 | 防什么 | 实现位置 |
|---|---|---|---|
| ① 章节级 | ledger 四态 `status==committed` | 整章重跑（重读原文/重分配 ID/重写文件） | `LedgerService`（确定性） |
| ② 记录级 | `record_id` / `path+record_id` | 同一 id 重复追加进数组 | `IndexWriter`（确定性） |
| ③ 内容级 | 文本/语义相似度 | 同一事实被 LLM 生成多个不同 id 的 claim/event | `dedupe_*` C 类工具（需语义） |

**一期只做 ①②，主动放弃 ③（C 类工具留桩）。** 放弃 ③ 可接受的理由：
- 单章内重复已被 ② 的 `claimed_locals` 挡住；
- 跨章重复不是「错」而是「冗余」，audit 的 `check_orphan_claims` 可兜底发现，
  下游解说检索按 claim 语义去重也能扛；
- 一期目标是跑通链路，不是建出无冗余的完美索引。

**记录级判重（②）的两个落点**（迁移自 demo `index_writer.py`）：
- `_append_root_entry`：`record_id not in existing` 才向 `entries[]` 追加（templates
  §3.7「同一索引内按 path+record_id 去重」）。
- `_write_events_block`：`claimed_locals` 集合保证同一 claim 的 `local_id` 只内联
  一次，后续事件重复声明时改走 `trigger_refs` 引用而非再次内联。

**ID 分配幂等约束（03 §4.7 反模式警示，一期实现边界见 D6）**：IdAllocator 只负责
单调递增分配，持久化高水位；「先分配后写文件」允许空号。理想情况是 `write_chapter`
入口读 ledger、`allocated_ids` 非空则复用；但一期只做到「committed 章跳过（不重跑
不重 allocate）」，applying 中途失败的精确复用推迟二期（见 D6）。

### D6 · P2c 迁移修正（IndexWriter + deepread 编排）

迁移 demo `index_writer.py` 时做的 6 处修正（demo 不能照搬）：

| 修正 | 说明 |
|---|---|
| C1 写盘规范统一 | demo `_write_json` 无 `sort_keys`，但 skeleton/fingerprint 用 `sort_keys=True`。指纹必须一致，IndexWriter 写盘改用 `fingerprint.json_bytes`（键按 Unicode 码点排序）+ `markdown_bytes` |
| C2 ledger 分离 | demo `_write_chapter_ledger` 直接写 `committed`（无四态）。改为 deepread 节点用 `LedgerService` 流转；`write_chapter` 返回 `allocated_ids` 供节点写入 ledger |
| C3 NameIndex 锚定 | 复用 P2a 的 NameIndex（锚定 name_catalog），纠正 demo 从 characters 反推 |
| C4 修复 bug | demo `_append_entity_stage_entry` 硬编码 stage 序号，改为显式传参 |
| C5 schema 兼容 | relationship/emotional 兼容 04-prompt §2.2 的 `snapshot` 嵌套（非 demo 平铺 `facets`） |
| C6 allocated_ids 完整收集 | demo 只收 claim/ev，漏 char/setting/rel/thread；改为 `_allocate` 统一收集 |

**ledger 四态流转**（deepread 每章）：`prepare` → LLM 抽取 → `write_chapter` →
`record_extraction`（写 allocated_ids+extraction，→extracted）→ `transition
(extracted→applying)` → `commit`。

**一期恢复语义（决策 5）**：崩溃/重跑时从 cursor=1 重新遍历，committed 章 O(1)
跳过，未 committed 章重试。一期**不精确复用** applying 中途失败的 allocated_ids
（会重新 allocate 留空号 + 可能重复 append 部分业务记录），由 audit 兜底；仅靠
「committed 跳过」这道闸保证不重复定义已提交记录。

**一期 halt 语义**：audit 未实现 + 无运行中暂停机制，deepread 的 halt（连续 ≥3
章 error_limit）后返回 `phase="done"` + `halt_reason`，任务结束；用户重新 POST
任务（build_mode=resume）靠 ledger 幂等跳过已 committed 章续跑。

**进度可观测（决策 4）**：deepread 单节点内逐章写 `_staging/progress.json`（含
current/total/published/halt_reason）+ 更新 `manifest.published_through`。
`query_build_status` 轮询此文件，不依赖 graph checkpoint（节点内不会即时 checkpoint）。

### D7 · P3 迁移修正（audit 工具 + issue 落盘）

迁移 demo `audit_simple.py` 时做的修正（demo 不能照搬）：

| 修正 | 说明 |
|---|---|
| C1 参数化 | novel_root / novel_id 参数化（demo 硬编码 `AUDIT_NOVEL_ROOT` 环境变量 + `"wukon"`） |
| C2 模型工厂 | `create_chat_model(config)` 而非 `init_chat_model` |
| C3 Agent 装配 | `create_agent` 原语 + Pydantic 兜底校验（对齐 P2 决策），而非 demo 的 `bind_tools` 结构化提交 |
| C4 issue ID 分配 | `IdAllocator.allocate("issue")` 而非 demo 手动 `hw+1` |
| C5 分片规则修正 | 用 `ceil(opened_at/20)` 对齐 skeleton 的「每 20 章一分片」；demo/04 §2.1 的「61+→block-0004」是简化示例，与 skeleton `math.ceil(total/20)` 实际分片冲突 |
| C6 staging 路径 | `check_stage_integrity` 检查 `_staging/stages/{stage_id}.commit.json`（P2c 实际位置），非 demo 的 `_staging/deepread/stages/` |
| C7 空号误报 | `check_id_conflict` 不报「空号」（03 §4.7「先分配后写文件允许空号」），只报「重复」+「超发」（文件最大编号 > 高水位） |

### D8 · N7 human_review_issues 三态 + 一期边界

N7 复用 D2 的 interrupt 机制：`interrupt_before=["review_issues"]`，resume 时决策写
`pending_human_decision`，节点据此路由：
- `fixed` → phase=`audit`（重新审计验证人工修复）
- `skip` → phase=`done`（derive 推迟，直接结束）
- `stop` → phase=`done`

**一期收窄（需澄清的设计张力）**：04 文档 §2.2 的分流表（`correct_safe_through` /
`patch_record` 自动修复）与 §0.1「critical 阻断发布进 N7」存在张力——自动修复依赖
读原文定位，而 §0.1 明确「一期不读原文、自动修复留二期」。故一期统一收窄为：

| 一期边界 | 说明 |
|---|---|
| 不实现自动修复 | 所有 issue 一律落盘 `quality/issues/`；`repair_suggestion` 只保留在 `_staging/audit/report.json` 供人工参考，不触发 CAS 修复 |
| 不实现 issue 状态流转 | `open→resolved` 是 04 §3 待办；`fixed` 重审计会重复落盘 issue（接受冗余，靠 `audit_summary` 反映最新情况） |
| 无 critical → done | derive 推迟，故 audit 无 critical 直接 `phase=done`（不经过 derive） |
| 审计失败不静默成功 | LLM 审计失败（重试 2 次仍失败）或「有章节但无 committed」时，落 `_staging/audit/error.json` + 抛异常让 task `failed`（error 可见）；不再降级为 `done` 伪装「审计通过」。空小说（total_chapters=0）仍合法 `done` |

### D9 · 节点 agent 流式化（进度查询完善）

**问题**：节点此前用 `agent.ainvoke(...)` 一次性调用 `create_agent` 返回的子 agent，
整个执行过程（工具调用 / 思考 / 中间 message）被吞掉，只返回最终 result。外层
`runtime.run_task` 的 `graph.astream(stream_mode=["updates","messages"])` 只能捕获
节点边界（updates），捕获不到节点内部 agent 的微观事件——SSE 里只有 `node` 事件，
看不到 `tool_call` / `tool_result` / `message` / `reasoning`。

**解决**（对齐 narration 已验证的模式）：

1. 新增 `agents/runner.py::run_agent_streaming(agent, prompt, config)`：统一用
   `agent.astream(stream_mode="messages")` 流式消费，`parse_stream_chunk` 解析事件，
   `emit_event` 透传，返回最终文本（JSON 字符串）供节点 `_parse_json`。
2. 节点（prescan/deepread/audit 共 5 处）从 `ainvoke` 改为 `run_agent_streaming`。
3. `runtime.run_task` 在执行前 `set_stream_emitter(_index_event_sink)` 绑定 contextvar
   事件桥，sink 把事件 `put_nowait` 进 `record.event_queue`；finally 里解绑。

**关键约束**：
- contextvar 桥（`stream._stream_emitter`）在同一 asyncio task 内传播。run_task 用
  `asyncio.create_task` 启动，但 `graph.astream` → 节点函数 → agent.astream 全在同一
  await 链上，不跨 task，故 contextvar 可靠。prescan 的 `asyncio.gather` 并发扫描
  也不分叉新 task，事件会交错（符合并发语义）但仍能透传。
- `run_agent_streaming` 用 `is_tool_activity` 重置 `final_text`：工具活动前的文本是
  「中间话」（如「我先读一下文件」），工具活动结束后重新累计最终 JSON；`_parse_json`
  用贪婪正则 `\{[\s\S]*\}` 提取首个 JSON 对象，前缀文字不影响解析。
- 预算硬兜底：新增 `config.index_max_tool_calls` / `config.index_token_budget`
  （默认 100 / 200000），与 narration 预算同构但独立。

### D10 · LLM 空输出防护 + prescan 重试（task failed 定位）

**故障现象**：任务在 `phase=skeleton` 报 `error="Expecting value: line 1 column 1
(char 0)"` 而 failed。但实际 skeleton（零 LLM）已正常完成（`source/index.json` /
`manifest.json` 均已落盘），真正失败点在 **prescan**——`prescan` 的 LLM 调用返回空
文本时，`_parse_json("")` → `json.loads("")` 抛误导性的 JSON 解析错误；且 prescan 的
scan/merge **没有重试**（deepread ≤3 次、audit ≤2 次，唯独 prescan 缺），一次 LLM
抖动就直接 failed。phase 停在 `skeleton` 是因为 prescan 节点未正常返回，updates 事件
没触发 `set_phase("prescan")`。

**修复**：

1. `runner.py::run_agent_streaming` 末尾加空输出检测：`final_text` 为空时抛明确
   `RuntimeError`（区分「预算超限」与「LLM 返回空」），不再让上游 `_parse_json("")`
   抛误导性的 `Expecting value`。
2. `prescan.py` 的 `scan_one`（单卷扫读）与 `merge`（阶段合并）各加重试 ≤2 次，
   与 audit 对齐；重试耗尽后抛带卷 id / 上下文的明确错误。

**教训**：LLM 偶发返回空是常态（代理抖动 / 模型瞬时异常），所有调 LLM 的节点必须
有「重试 + 空输出显式报错」两层防护，否则 error 信息会退化成底层 JSON 异常，掩盖
真实根因（本次就是因为 `Expecting value` 让人误以为是 skeleton 的文件解析问题）。

### D11 · reasoning 流截断 → ainvoke 降级重试

**根因**：DeepSeek v4.1 flash 是 reasoning 模型。流式输出（`stream_mode="messages"`）
时，会先输出大量「思考」（content 为空的 AIMessageChunk，实测 754 个 chunk 中前 752
个 content 为空）+ 中间 `read_file` 工具调用，**最后 1~2 个 chunk 才输出正式 JSON**。
当 LLM 服务抖动、流在「输出正式 JSON 前」被截断时，`final_text` 累计为空，`run_agent_streaming`
抛「未产出任何文本」。且同一 prompt 重试可能倾向一致失败（reasoning 路径固化），
导致 merge「重试 2 次仍失败」。

**关键证据**：`agent.ainvoke`（非流式、等完整执行）返回的 `result["messages"]` 中，
中间有 `ToolMessage`（read_file 结果，说明 merge 真的调了工具）与 content=0 的
AIMessage（思考），最后一条 AIMessage 的 `content` 是完整 JSON（1298 字符）。

**修复**：

1. `runner.py::run_agent_streaming` 流式空输出时，降级用 `agent.ainvoke` 非流式重试
   一次，从 `result["messages"][-1].content` 取最终结果（绕过流式 chunk 截断）。
   降级路径不透传微观事件（属兜底，可接受）。deepread / audit 经 runner 自动获得此保护。
2. `prescan.py` 的 `scan_one` / `merge` 重试从 2 次提到 3 次，并加指数退避
   （`asyncio.sleep(2 * (attempt+1))`），给服务恢复时间。

**教训**：reasoning 模型的流式输出「思考长、正式内容最后才出」，服务抖动时流式极易
截断为空。对「要求输出完整结构化 JSON」的子 agent，空输出降级到 `ainvoke`（等完整
执行）是比单纯重试更可靠的兜底，因为绕开了流式 chunk 的截断窗口。

### D12 · 子 agent 单次输出 max_tokens 上限（防大 JSON 截断）

**问题**：`create_chat_model` 此前不设 `max_tokens`。DeepSeek 默认单次输出上限仅
4096 token，而 index_builder 子 agent 输出的是**结构化 JSON**，大输出场景（
stage_commit 多实体多关系、audit 全书多 issue、chapter_react 单章多 claim）单次输出
很容易上万 token，超出默认上限会被截断，导致 `_parse_json` 抛 JSON 解析错误。reasoning
模型的「思考」与正式 JSON 还共享这份输出预算，加剧截断风险。

**修复**：

1. `model.py::create_chat_model` 新增 `max_tokens: int | None = None` 参数（None 不设限，
   用模型默认）。与 `temperature` 不同，`max_tokens` 是**任务级**输出预算（不同任务
   输出量级差异大），故不放 `ModelSettings`（模型连接信息），由调用方按任务传入。
2. `config.py` 新增 `index_max_tokens: int = 32768`（index_builder 子 agent 专属）。
3. 5 个 index_builder 子 agent（scan_vol / stage_plan_merge / chapter_react /
   stage_commit_react / audit_analyze_react）统一传
   `max_tokens=config.index_max_tokens`。

**为什么 32768（不是 4096 或 8192）**：这些是离线批处理任务（一次性跑完），正确性
优先于 token 成本；reasoning 模型的「思考」可能占数万 token，正式 JSON 又可能上万
token，32768 给两者都留足空间，同时仍是一个明确上界（防止无限思考失控）。若极端
大输出场景（超长卷 stage_commit）仍被截断，调大 `config.index_max_tokens` 即可。

### D13 · list_dir 返回 PosixPath 导致 JSON 序列化失败

**问题**：`tools/source.py::build_source_tools` 里的 `list_dir` 用
`for name in sorted(target.iterdir())` 遍历目录，`target.iterdir()` 返回的是
`PosixPath` 对象（不是字符串），`sorted` 后仍是 `PosixPath`。代码把 `name` 直接塞进
dict 再 `json.dumps`，触发 `Object of type PosixPath is not JSON serializable`，被
`except` 捕获后返回 `(列出失败: ...)`，导致 ScanVolReActAgent / StagePlanMergeAgent
无法列目录、prescan 阶段失败。

**根因**：`pathlib.Path.iterdir()` / `.glob()` / `.rglob()` 返回的都是 `Path` 对象，
必须显式转字符串（`.name` 取文件名 / `.as_posix()` 取相对路径 / `str()`）后才能
JSON 序列化。同为 `list_dir` 的另外两个实现（`ReadOnlyFs.list_dir` 用 `.as_posix()`、
`LocalSandbox.list_dir` 用 `.as_posix()`）都正确转成了字符串，唯独这里漏了。

**修复**：遍历变量改 `entry`，`entries.append({"name": entry.name, ...})` 用 `.name`
转成文件名字符串（与 docstring 的 `name` 语义「条目名称」一致，`path` 字段单独承载
传入的 `rel_path`）。

**教训**：任何把 `pathlib.Path` 派生对象（iterdir/glob/rglob 产物）直接放进
`json.dumps` / dict 后序列化的地方都是隐患，必须第一时间转字符串。这类错误在工具
函数里被 `except` 吞掉后不会冒泡到上层，只会变成一条误导性的 `(列出失败: ...)`，
排查时容易绕远路。

### D14 · prescan 全量并发触发服务端限流（429）

**问题**：`prescan` 用 `asyncio.gather` **全量并发**扫描所有卷。长篇小说几十卷时，
N 个 `ScanVolReActAgent` 同时启动，每个 agent 又含多轮 LLM turn（reasoning 模型
「思考→调工具→再思考→输出」），瞬间产生 N × 多轮的并发请求，打爆公共模型服务的
频率/并发限流（`429 - 当前使用的公共模型服务, 并发有限; 当前的限流为: 100/min`）。
原重试退避只有 2s/4s，对 60s 的限流窗口无效，且所有卷**同时**退避、**同时**重试，
形成请求风暴，导致「重试 3 次仍失败」。

**修复**：

1. `config.py` 新增 `index_scan_concurrency: int = 3`（prescan 并发扫卷数上限）。
2. `prescan.py` 用 `asyncio.Semaphore(config.index_scan_concurrency)` 包裹 `scan_one`，
   把同时在跑的卷数限制到 3（gather 仍创建全部协程，但未获信号量的协程阻塞等待，
   不发请求）。
3. 新增 `_is_rate_limited(exc)`：识别 429 / 限流 / rate limit，对此类错误用
   `15s / 30s` 长退避（限流窗口 60s，短退避无效），普通错误仍走 2s/4s 退避。
   merge 阶段同样加 429 识别。

**为什么并发 3 而不是串行 1**：串行最稳但几十卷逐卷扫太慢（每卷几秒~几十秒）。
受控并发 3 是折中——把请求速率压到限流窗口内（100/min 对 3 个并发 agent 的 turn
数量级是充裕的），同时保留并发加速。若仍 429，可下调 `index_scan_concurrency` 到
2 或 1。

**教训**：调用有频率/并发限流的外部 LLM 服务时，「全量并发 fan-out」是危险模式，
必须用 Semaphore 受控并发 + 针对 429 的专门长退避；普通错误退避（秒级）对限流窗口
（分钟级）无效。此经验同样适用于 deepread 若未来改为并发逐章精读（当前是串行 while
循环，无此问题）。

## 文件结构

```
index_builder/
├── state.py           # BuildState（P0+P1 裁剪版，P2/P3 增补 deepread 游标 + audit_issues）
├── graph.py           # build_index_graph + build_initial_state
├── nodes/
│   ├── skeleton.py    # 迁移 4 个脚本（切块/骨架/分片/校验）
│   ├── prescan.py     # fan-out 扫卷 + fan-in 合并 + 确定性落盘
│   ├── review_plan.py # Human-in-Loop interrupt 载体（N4）
│   ├── deepread.py    # P2 核心：逐章精读 while 循环 + ledger 四态 + stage 聚合
│   ├── audit.py       # P3：LLM 审计 + issue 确定性落盘 + 分流（N6）
│   └── human_review_issues.py # P3：Human-in-Loop interrupt 载体（N7）
├── agents/
│   ├── scan_vol.py            # ScanVolReActAgent（prompt 来自 04-prompt §2.2）
│   ├── stage_plan_merge.py    # StagePlanMergeAgent（prompt 来自 04-prompt §3.2）
│   ├── schemas.py             # ChapterExtraction / StageCommitPayload / AuditResult 输出契约
│   ├── chapter_react.py       # ChapterReActAgent（prompt 来自 04 §1.2）
│   ├── stage_commit_react.py  # StageCommitReActAgent（prompt 来自 04 §2.2）
│   ├── audit_analyze_react.py # AuditAnalyzeReActAgent（prompt 来自 04-prompt_审查 §1.2）
│   └── runner.py              # run_agent_streaming：子 agent 统一流式执行 + 事件透传
├── tools/
│   ├── source.py      # A 类：list_dir/read_file（prescan）+ read_source/read_source_window（deepread）
│   ├── common.py      # 工具公共 helper：Ref 解析 / JSON 读取 / 章节索引构建
│   ├── entity.py      # B 类：resolve_name / fetch_entity_current / lookup_stage
│   ├── dedupe.py      # C 类：dedupe_claim / dedupe_event / find_similar_relationship（一期留桩）
│   ├── stage_query.py # E 类：fetch_entity_summary / fetch_event_detail / fetch_related_claims / list_entity_stages
│   └── audit.py       # F 类：5 个检查工具（check_ref_reachability 等，只读确定性）
├── services/
│   ├── fingerprint.py  # SHA-256 指纹（对齐 skeleton._json_dumps 规范）
│   ├── id_allocator.py # ID 高水位（ledger/id-state.json）
│   └── name_index.py   # 名字归一/查找（锚定 navigation/names/ name_catalog）
├── writes/
│   ├── ledger.py       # LedgerService 四态状态机（P2a 核心）
│   └── index_writer.py # IndexWriter 确定性落库器（P2c，迁移 demo + 6 处修正）
└── __init__.py
```

## 二期待办

- prescan 幂等（_staging done 标记）
- checkpointer 切 sqlite（跨重启恢复）
- derive 节点（向量索引，已推迟）
- name_lookup 分片拆分（按首字/容量，一期单分片）
- C 类 dedupe 真实语义去重 + E 类 fetch_related_claims 真实查询
- ledger operations 指纹 CAS 逐目标重放 + applying 中途失败 allocated_ids 精确复用
- audit 自动修复（correct_safe_through / patch_record 的 CAS，依赖读原文）+ issue 状态流转（open→resolved）
- N7 resume 的 `fixed` 语义闭环（当前只重审计，不校验具体修复项）

## 实施进度

| 子任务 | 内容 | 状态 |
|---|---|---|
| P2a | services（id_allocator/name_index/fingerprint）+ writes/ledger 四态 + state/graph 接入空壳 deepread | ✅ 完成 |
| P2b | tools（A/B/C/E 类）+ chapter_react + stage_commit_react（prompt 抄全 + schemas） | ✅ 完成 |
| P2c | nodes/deepread while 循环 + writes/index_writer（迁移 + 修正） | ✅ 完成 |
| P3 | tools/audit（F 类 5 工具）+ audit_analyze_react + nodes/audit + nodes/human_review_issues + interrupt | ✅ 完成 |
| P4 | 进度查询完善、错误恢复、离线重放（replay_write / archive_staging） | ⏳ 待做 |
