# tasks 模块设计说明

## 定位

通用「长任务运行时」：索引生成（index_builder）与未来的长解说任务共用。解决三个此前
设计文档未落地的诉求：

1. **异步执行载体**（问题 1）：`build_novel_index` 不再同步阻塞 lead_agent，而是
   `POST /api/tasks` 立即返回 `task_id`，后台协程驱动 graph 执行。
2. **SSE 实时进度 + 执行详情**（问题 2）：`POST /api/tasks/{id}/stream` 订阅事件流，
   宏观进度用 `node` 事件（当前阶段），微观详情复用 stream 协议（tool_call /
   tool_result / message / reasoning）。
3. **暂停/恢复通用化**（问题 3）：用 LangGraph interrupt 实现 Human-in-Loop 暂停，
   `POST /api/tasks/{id}/resume` 携带决策恢复。

## 与 runs 模块的边界（为什么不复用 RunManager）

| 维度 | runs（对话 run） | tasks（长任务） |
|---|---|---|
| 标识维度 | `thread_id` | `task_id` |
| 生命周期 | 秒~分钟 | 小时~天 |
| 状态机 | pending/running/success/error/interrupted | + `paused`（等待人工） |
| 持久化 | 内存态 | sqlite（TaskStore） |
| 消费方式 | `stream_mode="messages"` | `["updates", "messages"]` |

强行合并二者会让 RunManager 职责爆炸，故独立建 tasks 模块。

## 关键决策

### D1 · 决策 A2：task 记录 sqlite 持久化

`TaskStore` 用 stdlib sqlite3（对齐 SpaceStore 风格），持久化 task_id / novel_id /
kind / status / phase / error / 时间戳。重启后 `GET /api/tasks` 仍能 list 历史任务。
**运行时字段（协程 / 事件队列 / 取消信号）不落盘**，随进程生命周期。

### D2 · checkpointer 一期用 InMemorySaver

`build_index_graph` 默认 InMemorySaver，支持 interrupt + **进程内** resume。
跨进程重启恢复（需 AsyncSqliteSaver）留待二期。注意：D1 的 task 记录持久化与
checkpointer 是两层——前者保证「能看到历史任务」，后者保证「能从断点继续执行」。
一期只做前者。

### D3 · 决策 B1：一期只做 REST API，不挂 lead_agent 工具

`POST /api/tasks` 直接触发（前端点按钮），暂不做 `build_novel_index` 工具挂进
lead_agent（对话式触发）——方便调试。二期再挂工具时，只需把「提交任务」封装成
tool 返回 task_id，tasks 运行时无需改动。

### D4 · 决策 C1：一期只做 Human-in-Loop interrupt

只支持 `review_plan` / `review_issues` 两个人工审核点的暂停（`interrupt_before` +
resume），不做「运行中强制暂停」（prescan/deepread 内部的 pause_event 检查点）。
后者二期在 deepread 的 while 循环里补。

### D5 · 事件桥用事件队列，不用 contextvar

runs 的内层透传用 `stream.set_stream_emitter`（contextvar，同 async task 传播）。
tasks 的后台协程是**独立 task**，contextvar 不跨 task，故改用 `record.event_queue`
（asyncio.Queue）：后台协程 `put_nowait` 事件，SSE 端点 `get` 消费，终态放 `None`
哨兵结束流。事件带 `source="index"`。

### D6 · 事件协议扩展（stream.py）

新增：
- `EVENT_NODE = "node"`：节点进度事件，字段 `node`（节点名）/ `status`（enter|exit）。
- `SOURCE_INDEX = "index"`：索引生成长任务的事件来源。

### D7 · resume 只接受 paused + 决策校验 + abort_event 重置

`resume` 的硬约束（manager 层 + 路由层双重校验）：
- **状态门槛**：只有 `paused` 可恢复；`cancelled`/`failed`/`done` 一律拒绝（409），
  需重新创建任务。原因：`cancelled` 是进程重启或手动取消的产物，InMemorySaver 的
  checkpoint 已丢，无从恢复。
- **决策格式**：`decision` 必须为 `{"decision": "approve" | "reject" | "fixed" | "skip" | "stop"}`；
  否则 400。`approve`/`reject` 对应 `review_plan`，`fixed`/`skip`/`stop` 对应
  `review_issues`。Swagger 默认示例 `{"additionalProp1": {}}` 会被
  `decision.get("decision")` 判 None 拒绝，避免「无决策进入 interrupt 节点 →
  phase 不变 → 死循环」。
- **abort_event 重置**：resume 复用同一 `record`，若此前 `cancel` 过会残留已置位的
  `abort_event`，导致 resume 后 `run_task` 一进来就再次 cancelled。故 resume 前
  `record.abort_event.clear()`。

### D8 · 进程重启对账（僵尸任务治理）

`TaskManager.__init__` 调 `_reconcile_stale_tasks()`：把 sqlite 里遗留的非终态
（pending/running/paused）任务统一标记 `cancelled`。因为 checkpointer 一期用
InMemorySaver，graph 执行态随进程丢失，记录虽在（D1）但执行态不在（D2），遗留的
「running/paused」都是僵尸。二期切 AsyncSqliteSaver 后，paused 可跨重启保留，届时
本方法应改为只对 pending/running 对账。

### D9 · interrupt 时 phase 显示待执行节点

`runtime.run_task` 检测到 interrupt 后，用 `graph.get_state(config).next[0]` 作为
`phase`（即 `review_plan`），而非停留在上一个已完成的 `prescan`。这样前端看到
`status=paused, phase=review_plan`，语义一致：明确「正在等 review_plan 的人工决策」。

### D10 · `TaskRecord.phase` 的双重语义（运行中 vs 终态）

`phase` 字段有两个取值来源，语义不同、需区分：

| 时机 | 取值来源 | 语义 | 示例 |
|---|---|---|---|
| 运行中（节点退出） | updates 事件的节点名 `set_phase(node_name)` | 「当前/刚完成的阶段」 | deepread 执行完 → `phase=deepread` |
| interrupt 暂停 | `state.next[0]` 待执行节点名 | 「正在等哪个节点的人工决策」 | 挂起在 review_plan 前 → `phase=review_plan` |
| 终态 done | `state.values["phase"]`（最终阶段） | 「任务最终到达的阶段」 | audit 无 critical → `phase=done` |

**关键坑（D10 的来源）**：若终态 done 时沿用「节点名」，会显示成 `status=done` 而
`phase=audit` 的矛盾组合——因为最后退出的节点是 audit，但 audit 内部已把 state.phase
流转到 `done`。故 `run_task` 在 `else`（正常结束）分支必须用
`state.values["phase"]` 覆盖，把 phase 切回最终阶段 `done`，与 `status=done` 对齐。

### D11 · 节点内微观事件透传（contextvar 事件桥）

**问题**：index_builder 节点内部用 `ainvoke` 调用子 agent 时，工具调用/思考过程被吞掉，
SSE 里只有 `node` 事件，看不到 `tool_call` / `tool_result` / `message` / `reasoning`。

**解决**：`run_task` 在执行 `graph.astream` 前 `set_stream_emitter(_index_event_sink)`，
sink 把事件 `put_nowait` 进 `record.event_queue`；finally 里 `set_stream_emitter(None)`
解绑。节点内部（index_builder）用 `run_agent_streaming` 流式消费并 `emit_event` 透传。

**为什么 contextvar 在这里可靠（与 D5 不冲突）**：D5 说「tasks 后台协程是独立 task，
contextvar 不跨 task」——指的是 run_task 与 SSE 端点之间不共享 contextvar，所以 SSE
走 event_queue。但 run_task → graph.astream → 节点函数 → agent.astream 全在同一 await
链上（同一 asyncio task），contextvar 在此链内传播是可靠的。故 sink 直接写 event_queue，
两端在「run_task 内绑定 / 节点内 emit」这条链上衔接，最终仍由 SSE 端点从 queue 消费。

## 文件结构

```
tasks/
├── schemas.py    # TaskStatus / TaskRecord
├── store.py      # TaskStore（sqlite 持久化）
├── manager.py    # TaskManager（start/resume/cancel/get/list + set_status/set_phase/emit）
├── runtime.py    # run_task（后台协程：graph.astream + 事件桥 + 中断检测）
└── __init__.py
```

## resume 的实现方式

用 `graph.update_state(config, {"pending_human_decision": decision})` 注入决策，
再 `graph.astream(None, config)` 从 checkpoint 继续（不用 `Command(resume=...)`，
与设计文档 §4.4 场景 B 一致）。中断检测：`graph.get_state(config).next` 非空 →
paused（interrupt 挂起），空 → done。
