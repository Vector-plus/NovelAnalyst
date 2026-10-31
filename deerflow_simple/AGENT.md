如果有重要的系统决策更新需要同步更新本文件

## Agent 迭代上限（recursion_limit）

- **背景**：langchain 1.x 的 `create_agent` 已移除 `max_iterations` 参数，agent 在「模型不再返回
  `tool_calls`」时自然终止，无固定步数上限。唯一的硬限制是 `create_agent` 源码里硬编码的
  LangGraph `recursion_limit = 9999`（super-step 递归上限）。
- **决策**：新增 `SimpleConfig.recursion_limit`（默认 9999），作为可调的安全阈值，防 agent 异常
  死循环跑爆预算。它不是「迭代步数」，而是 LangGraph 层递归上限。
- **注入点**（3 处真实调用）：
  - `runs/worker.py::submit_run`：构造 `RunnableConfig` 时写入 `recursion_limit`（lead_agent 的
    `graph.astream`）。
  - `subagents/executor.py::execute`：`graph.invoke` 传 `config={"recursion_limit": ...}`。
  - `narration/generate_narration.py::generate_narration`：NarrationAgent 的 `agent.astream` 传
    `config={"recursion_limit": ...}`。
- **注意**：`recursion_limit` 是 RunnableConfig 的**顶层**字段，必须与 `configurable.thread_id`
  平级，不能放进 `configurable` 里。

## 预算守护（工具调用次数 + token 上限，双层硬约束）

**背景**：`recursion_limit` 只是 LangGraph 的 super-step 递归上限，**不是**工具调用次数，也不是
token 预算。`create_agent` 已无 `max_iterations` 参数，agent 失控时可能反复调用工具 / token 跑爆。
SKILL.md 的 `task_token_budget` 只是给 LLM 的软约束，不可靠。

**方案**：把预算守护抽成可复用的 `stream.py::BudgetGuard`（累计工具调用次数 + token 估算），
在**两层**都加硬约束（纯代码，不依赖 LLM 自觉）：

| 层 | 消费循环位置 | 配置字段 |
|---|---|---|
| lead_agent 层 | `runs/worker.py::run_agent` | `agent_max_tool_calls` / `agent_token_budget` |
| NarrationAgent 内层 | `narration/generate_narration.py::generate_narration` | `narration_max_tool_calls` / `narration_token_budget` |

**核心机制**：
1. 用 `stream_mode="messages"` 消费，`parse_stream_chunk` 解析出事件后 `guard.feed(ev)`。
2. 工具调用次数：统计 `tool_result` 事件数（一次完整工具往返算一次）。
3. token 预算：`estimate_tokens`（中文 1 字≈1 token，英文 4 字符≈1 token）累计「循环增量」token。
4. `guard.check()` 任一超限即 `break` 中断流（已验证 `break` + `aclose()` 能真正停止工具执行）。

**关键教训（本次修复的根因）**：早期只在内层 NarrationAgent 加了预算守护，**lead_agent 层没有加**。
用户通过 `/api/runs/stream` 观察到的「很多 tool 调用」来自 lead_agent 层，而非内层。因此预算守护
必须**两层都加**，缺一层就等于没限制。

**预算耗尽的表现**：若还没写出正文（result_text / draft 为空），标记为 `error`（明确报错）；若已
有部分正文，返回 `success` + 不完整结果。均附 `budget_truncated` 标记（内层）或通过 error 提示（lead 层）。

**默认值**：`agent_max_tool_calls=20` / `agent_token_budget=32000`；`narration_max_tool_calls=5` /
`narration_token_budget=2000`（注意：narration 默认值较小，可能不适合完整长解说稿，可按需调大）。

## 单次输出 max_tokens（单次调用输出上限，与 BudgetGuard 互补）

`BudgetGuard` 防「跨多次工具调用的累计 token 失控」（死循环），`max_tokens` 防「单次模型输出被
服务端默认上限截断」（DeepSeek 默认 4096，超出则 JSON 截断）。二者互补，缺一不可。

- `model.py::create_chat_model` 新增 `max_tokens: int | None = None` 参数（None 不设限）。它是
  **任务级**输出预算，由调用方按任务传入，不放 `ModelSettings`（那里只放模型连接信息）。
- `config.index_max_tokens = 32768`：index_builder 各子 agent 统一传入（输出结构化 JSON，大输出
  场景单次可上万 token；reasoning 模型「思考 + 正式 JSON」共享该预算，需足够大）。
- 详见 `index_builder/AGENT.md` D12。

## 小说空间模块（spaces，纯后端）

- **定位**：小说空间的元数据 + 沙箱目录 + 原文 CRUD，纯后端、无 LLM 参与。对应产品化的
  「创建小说空间」与「空间内原文增删改查」两个能力。
- **id 即 novel_id**：`NovelSpace.id`（uuid4 hex）就是解说词模块的 `novel_id`，
  小说空间根（space root）为 `config.workspace_path / id`。
- **路径分三类目录（核心，避免工具找不到路径）**：
  - **space root** = `config.workspace_path / id`：存原文 `source/novel.txt`（spaces 模块管理）。
  - **index root** = `config.workspace_path / id / novel`：存 `manifest.json` 与各主题索引
    （novel-index-creator 生成，`INDEX_DIR = "novel"`）。
  - **result dir** = `config.workspace_path / id / result`：存生成完成的解说词稿件
    （narration 产出物，`RESULT_DIR = "result"`，由 `resolve_novel_result_path` 解析）。
  - narration 解说词检索锚定 **index root**（只读消费），产出物写 **result dir**；
    spaces 原文 CRUD 锚定 **space root**。三者语义不同、不可混用。
- **novel_id 是所有小说操作的统一入口键（核心约定）**：创建空间后产生 `novel_id`，后续对这本
  小说的**任何**操作都必须显式传入 `novel_id`。已落地：原文 CRUD（`/api/spaces/{id}/source`）、
  解说词生成；后续索引创建（`build_novel_index`）同样遵循。
  意义：空间隔离（一本小说一个沙箱目录）、路径确定性（novel_id 唯一映射到 space root / index root）。
- **解说词 novel_id 由代码注入（InjectedState，不交给 LLM 决策）**：`generate_narration` 的
  `novel_id` 参数用 `Annotated[str | None, InjectedState("novel_id")]` 标注，**不出现在 LLM 可见的
  tool schema 中**，由代码从 graph state 注入：用户创建对话时经 `client.chat(..., novel_id=xxx)`
  → `submit_run(novel_id)` → graph 输入 payload → `InjectedState` 注入工具。彻底消除 LLM
  幻觉/猜测 novel_id 的风险（替代早前的「对话提供」方案）。
- **路径映射单一来源（三类目录）**：`spaces/paths.py::resolve_novel_path` 是 id→space root 的唯一实现；
  `spaces/paths.py::resolve_novel_index_path` 是 id→index root 的唯一实现（内部复用
  `resolve_novel_path` + `INDEX_DIR`）；`spaces/paths.py::resolve_novel_result_path` 是
  id→result dir 的唯一实现（内部复用 `resolve_novel_path` + `RESULT_DIR`）。
  narration 的 `resolve_novel_root` 复用 `resolve_novel_index_path`（只额外做存在性校验）。
- **元数据存储**：stdlib `sqlite3`，文件在 `config.spaces_db`（默认 `.deerflow_simple/spaces.db`），
  不引 ORM。
- **原文存放约定**：`novel_root/source/` 下唯一一个文件 `novel.txt`（常量 `SOURCE_FILE`），统一
  UTF-8 落盘；上传走 `multipart/form-data`，后端用 charset-normalizer 探测原始编码
  （GBK / GB18030 / Big5 等）后转 UTF-8。
- **安全护栏**：`resolve_novel_path` 做路径穿越防护（`is_relative_to`）；原文为唯一固定文件、
  无用户输入路径，故无路径穿越面。
- **依赖提示**：HTTP 层（spaces 路由 + app）需要 `uv sync --extra server`（fastapi）。

## 路径锚定分层（通用沙箱 vs 小说专用工具）

排查确认的关键边界，指导「小说文件访问」的正确实现方式，避免 future 工具调用找不到路径：

- **通用沙箱工具**（lead_agent 的 `bash`/`read_file`/`write_file`/`ls`）锚定
  `config.workspace_path`（workspace 根），**不是**某个小说的 index root。它们是通用编程/文件
  操作入口，能访问 workspace 下所有小说目录（跨小说无隔离）。
- **小说文件访问必须走专用工具**（`generate_narration` / 未来的 `build_novel_index`），这些工具
  通过 `resolve_novel_index_path(novel_id)` 锚定 **index root**（`workspace/{id}/novel`），
  `novel_id` 由 `InjectedState` 代码注入。**注意：锚定的是 index root，不是 space root**——
  后者是存原文 `source/novel.txt` 的空间根，前者才是存 `manifest.json` 的索引根。
- **为什么 LLM 不会用通用沙箱误读小说文件**：`novel_id` 对 LLM 不可见（`InjectedState` 隐藏），
  LLM 无法拼出 `{novel_id}/novel/...` 定位具体小说，因此小说文件访问天然只能走专用工具。
- **未来 `build_novel_index`（索引创建写工作流）的实现约束**：需要一个**锚定 index root 的可写
  工具集**（不能复用 narration 的只读 `ReadOnlyFs`，也不能复用锚 workspace 根的 `LocalSandbox`），
  `novel_id` 同样用 `InjectedState` 注入。

## lead_agent prompt 定位：任务编排者 + 沙箱隔离约束

**问题**：用户经 `/api/runs/stream` 提交解说任务时，lead_agent 收到请求后**不会立即调用
`generate_narration`**，而是先用通用沙箱工具（`bash`/`ls`/`read_file`）扫描 workspace 下所有
小说目录，既浪费工具调用预算，又打破「一本小说一个沙箱」的隔离语义。

**根因**：早期 `build_default_system_prompt` 的「能力范围」把解说任务写成「检索索引目录、搜集
证据…」，误导 LLM 以为检索/读文件是自己的职责；且 prompt 未声明通用沙箱工具不得用于小说访问。

**修复**（`agent.py::build_default_system_prompt`）：
1. 明确 lead_agent 是**任务编排者，不是执行者**——只理解意图 + 下发任务，检索/撰稿/自检都在工具内部。
2. 新增「任务下发规则」：收到解说类需求必须**直接调用 `generate_narration`**，并给出
   `task_type`/`subject`/`focus_ranges` 的参数映射与必填规则；索引构建类需求告知走专门入口，
   不自行建索引。
3. 新增「沙箱隔离」：通用沙箱工具（`bash`/`read_file`/`write_file`/`ls`）只用于通用编程，
   **禁止**扫描小说目录/读索引；小说访问只能走 `generate_narration`；`novel_id` 由系统注入，
   LLM 无需也不应扫描。
4. 同步强化 `generate_narration` 工具 docstring 首句，声明其为「解说任务唯一入口」。

## HTTP 层（app）挂载解说工具 + 沙箱 bash 容错

1. **HTTP server 必须挂载 generate_narration 工具**：`app/app.py::create_app` 里用
   `build_generate_narration_tool(config)` 构建工具，挂进 `build_agent(config, extra_tools=[...])`。
   - 原因：若不挂载，lead_agent 收到「生成人物传记」等解说请求时**没有 generate_narration 工具**，
     只能瞎用通用沙箱工具探索（症状：回复「我先看看沙箱里…」），最终因误读二进制文件而崩溃。
   - `skills_dir=None` 时 NarrationAgent 内部 fallback 到默认 `examples/skills`。
   - novel_id 链路与 SimpleClient 一致：HTTP 请求体 `novel_id` → `submit_run(novel_id)` →
     graph state → `InjectedState` 注入工具。

2. **沙箱 bash 工具容错解码**：`LocalSandbox.execute_command` 用 `subprocess.run(text=False)`
   （字节模式）+ 手动 UTF-8 解码（失败 `errors="replace"` 兜底）。
   - 原因：原来 `text=True` 会在 cat 二进制文件（如 sqlite db）时抛 `UnicodeDecodeError`，
     被 `run_agent` 的 `except Exception` 捕获后整个 run 变成 error。
   - 修复后 LLM 误读二进制文件只会拿到乱码，不会让 run 崩溃。

## 流式执行记录可见性（token 级 + 工具调用 + reasoning + 内层透传）

**目标**：把 LLM 执行过程（模型文本 / 推理内容 / 工具调用 / 工具返回）按流式逐 token 暴露给用户，
包括 lead_agent 层与内层 NarrationAgent 层。

**核心实现**（`stream.py` 统一事件协议 + contextvar 跨层事件桥）：

1. **统一事件协议**（`deerflow_simple/stream.py`）：所有层产出同一套结构化事件 dict：
   - `message`：模型文本 delta（token 级），字段 `content`。
   - `reasoning`：推理内容 delta（`reasoning_content`，DeepSeek-R1 等），字段 `content`。
   - `tool_call`：一次完整工具调用，字段 `name` / `args` / `tool_call_id`。
   - `tool_result`：一次工具返回，字段 `name` / `content` / `tool_call_id`。
   - `done`：终态，字段 `status` / `result`。
   - 每个事件带 `source` 字段（`lead` / `narration`）区分来源。

2. **`stream_mode="messages"` 取代 `"values"`**（`runs/worker.py::run_agent`）：
   - `messages` 模式输出 `(message, metadata)` 元组，`message` 是 `AIMessageChunk`（token 级）
     或 `ToolMessage`。
   - 通过 `stream.parse_stream_chunk` 解析成统一事件，回调 `on_event` 对外输出。
   - `AIMessageChunk.additional_kwargs["reasoning_content"]` 单独映射为 `reasoning` 事件，
     与 `content`（最终答案）分离，前端可独立渲染「思考」区。
   - 工具调用参数按 `tool_call_chunks[].index` 跨 chunk 累加。
   - **`tool_call` 事件提前 emit（关键时序修复）**：`tool_call_chunks` 的 `name`/`id` 在首个 chunk
     即确定，只有 `args` 是逐片流出的。因此 `parse_stream_chunk` 在「name 已确定且 args 累加完整
     （`_try_complete_args` 用 `json.loads` 成功判断）」时**立即** emit `tool_call` 事件，而非等到
     `ToolMessage`。否则 lead_agent 调用 `generate_narration` 这类耗时工具的 `tool_call` 会延迟到
     工具**完全执行完**才出现，被工具内部透传的内层事件淹没，造成「看不到工具调用」的假象。
     `ToolMessage` 阶段只补 emit `tool_result`（并对 args 始终未解析成功的极端情况兜底 emit `tool_call`）。

3. **跨层事件桥（contextvar）**：`stream.set_stream_emitter(on_event)` 把回调绑定到当前 async task；
   内层工具 `generate_narration` 在同一个 task 内 `emit_event(...)`，即可把内层 NarrationAgent 的
   事件透传回 lead_agent 的事件通道（**已验证**：LangGraph 执行 async tool 时 contextvar 同 task 传播）。

4. **内层 NarrationAgent 透传**（`narration/generate_narration.py`）：
   - `generate_narration` 从同步 `agent.invoke` 改为 `async def` + `agent.astream(stream_mode="messages")`，
     内层逐事件 `emit_event`（`source=narration`），同时累计最终 `draft`。
   - 这解决了解说词生成（耗时最长）此前过程不可见的问题。

5. **对外接口**：
   - HTTP SSE（`app/routers/runs.py`）：`/api/runs/stream` 把每个结构化事件以 `event` SSE 帧输出，
     事件类型为 `event`，data 为事件 dict；终态仍走 `run.finished`。
   - `SimpleClient.stream()`：从 `Iterator[str]` 改为 `Iterator[dict]`（yield 事件 dict）；
     新增 `stream_text()` 便捷方法（只 yield message 文本 delta，向后兼容）。

**边界说明**：
- 若底层模型不带 `reasoning_content`（如普通非推理模型），`reasoning` 事件自然不产出，
  代码无需特判——只是「有则转发、无则跳过」。
- 最终答案累计逻辑：遇到工具活动（tool_call/tool_result）时重置累计器，避免把「工具调用前的
  中间话」误当成最终答案。

## 数据目录路径锚定（消除 cwd 敏感，关键修复）

**问题根因**：`DS_HOME=.deerflow_simple` 是相对路径，早期 `data_dir` 直接返回
`Path(os.getenv("DS_HOME", ".deerflow_simple"))`（相对路径），`resolve_novel_path` 里
`config.workspace_path.resolve()` 才基于 **进程 cwd** 转绝对路径。后果：uvicorn 从
`NovelAnalyst/` 目录启动时，`.deerflow_simple` 被解析到 `NovelAnalyst/.deerflow_simple`
（空目录），而真实数据在 `deerflow_simple/.deerflow_simple/`，导致解说工具报
「小说索引目录不存在」。**症状**：同一份代码，`cd deerflow_simple` 跑能通过，HTTP server 跑却
找不到索引，且 `NovelAnalyst/.deerflow_simple/spaces.db` 被悄悄新建（空库）。

**修复**（`config.py`）：
- 定义 `_PROJECT_ROOT = Path(__file__).resolve().parent.parent`（即 `deerflow_simple/` 目录）作为
  所有相对路径的稳定锚点。
- 定义 `_resolve_path(raw)`：绝对路径原样返回；相对路径相对 `_PROJECT_ROOT` 解析（而非 cwd）。
- 应用到 `data_dir` / `memory_path` / `workspace_path` / `spaces_db` / `checkpointer_conn_str`。

**效果**：无论 uvicorn / python 从哪个目录启动，`DS_HOME=.deerflow_simple` 都锚定到
`deerflow_simple/.deerflow_simple`，跨启动目录一致；`cd deerflow_simple` 运行的行为不变
（该场景下 cwd 与项目根本就重合）。

**遗留**：修复前在 `NovelAnalyst/.deerflow_simple/` 产生的空 `spaces.db` 与空 `workspace/`
是脏数据，需手动清理（不影响代码逻辑，但会造成困惑）。

## 长任务运行时（tasks）与索引生成（index_builder）

**背景**：索引生成是「小时~天级」任务，与对话 run（秒~分钟级）生命周期完全不同，不能
复用 `runs.RunManager`（thread_id 维度、内存态、无 paused）。同时原设计文档的三个诉求
（异步执行载体 / SSE 进度 / 暂停恢复）都没有落地载体。

**方案**：新增两个模块（详见各自 AGENT.md）：
- `tasks/`：通用长任务运行时。task_id 维度、sqlite 持久化（决策 A2）、后台协程驱动
  graph、事件队列供 SSE 订阅、Human-in-Loop interrupt 暂停/恢复（决策 C1）。
- `index_builder/`：索引生成 graph（唯一 StateGraph，星型路由）。一期 P0+P1 只落地
  skeleton（切块/骨架/分片/校验，零 LLM）→ prescan（fan-out 扫卷 + fan-in 合并）→
  review_plan（interrupt）。

**三个决策落地**：
- 决策 A2：`TaskStore`（sqlite）持久化 task 记录，重启后 list 仍可见。
- 决策 B1：一期只做 REST API（`POST /api/tasks` + `POST /api/tasks/{id}/stream`），
  不挂 lead_agent 工具（方便调试）。
- 决策 C1：一期只做 Human-in-Loop interrupt（review_plan），不做运行中强制暂停。

**事件协议扩展**（`stream.py`）：新增 `node` 事件类型（宏观进度：当前阶段）与
`source="index"` 来源。微观执行详情（tool_call/tool_result/reasoning/message）复用
现有协议，由 `parse_stream_chunk` 透传。tasks 的事件桥用 `record.event_queue`
（asyncio.Queue，跨 task 不失效），不走 contextvar。

**对设计文档的两处纠正（不盲从）**：
1. `StagePlanMergeAgent` 原让 LLM 用 write_file 落盘 stage-plan，与 §5.10「写入全走
   确定性路径」冲突 → 改为 Agent 只产出 JSON，prescan 节点确定性落盘。
2. `scripts/` 的 4 个脚本是 CLI（argparse + 硬编码路径），不能 subprocess → 逻辑迁移
   为 `index_builder/nodes/skeleton.py` 包内纯函数。

**checkpointer 边界**：一期 index graph 用 InMemorySaver（支持 interrupt + 进程内
resume）；task 记录已由 TaskStore 持久化。跨进程重启恢复（AsyncSqliteSaver）二期做。

**novel_id 注入**：与 narration 一致，`build_initial_state` 经
`resolve_novel_index_path` 确定性映射 index root，不交给 LLM。