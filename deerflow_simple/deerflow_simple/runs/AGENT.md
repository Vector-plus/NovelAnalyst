# Runs 模块决策记录

## 流式执行记录（messages 模式）

- **背景**：早期 `run_agent` 用 `graph.astream(stream_mode="values")`，只在每个 super-step 结束后
  抛完整 state 快照，`on_chunk` 回调只提取 AI 文本，工具调用、token 流、工具返回全部丢失，
  用户看不到 LLM 执行过程。

- **决策**：改为 `graph.astream(stream_mode="messages")`，输出 `(message, metadata)` 元组，
  其中 `message` 是 `AIMessageChunk`（token 级，含 `content` / `reasoning_content` /
  `tool_call_chunks`）或 `ToolMessage`（工具返回）。

- **事件解析**：复用 `deerflow_simple/stream.py::parse_stream_chunk`，把 `(message, metadata)`
  解析成统一事件列表（`message` / `reasoning` / `tool_call` / `tool_result`），回调签名从
  `on_chunk(chunk: dict)` 改为 `on_event(event: dict)`。

- **跨层事件桥**：`run_agent` 消费流前 `set_stream_emitter(on_event)`，结束/异常时
  `set_stream_emitter(None)`。这样内层工具（generate_narration）在同一个 async task 内
  `emit_event(...)` 即可透传事件（contextvar 传播，无需显式传参）。

- **最终答案累计**：维护 `result_text`，遇到工具活动（tool_call/tool_result）时重置，
  确保 `RunRecord.result` 是最后一次模型输出的完整文本，而非工具调用前的中间话。

- **done 事件**：success / interrupted 时主动 `on_event({type: done, ...})`，但 HTTP SSE 层
  会跳过 done（终态统一由 `run.finished` 帧输出），`SimpleClient.stream` 则透传 done 供调用方感知终态。

如果有重要的系统决策更新需要同步更新本文件