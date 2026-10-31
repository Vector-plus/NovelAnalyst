# deerflow-simple

从 [DeerFlow](https://github.com/bytedance/deer-flow) 核心设计提炼出的**最小问答 agent 框架**。

DeerFlow 是一个庞大的生产级 super-agent（LangGraph + LangChain `AgentMiddleware`），
本仓库保留它的**九个核心子系统**，去掉 app 层、多余 provider 与企业级复杂度，把代码
从数千文件降到几十个文件，适合用来学习和理解 agent 框架的核心架构。

## 保留的核心功能

| 功能 | 对应模块 | 核心设计 |
|------|---------|---------|
| **Sub-Agents** | `deerflow_simple/subagents/` | `task` 工具委派给一次性编译的独立子代理 graph |
| **Progressive Skill Loading** | `deerflow_simple/skills/` | system prompt 只放技能索引，按需 `describe_skill` → `read_file` |
| **Skills & Tools** | `skills/` + `sandbox/` | `SKILL.md` 目录即技能；工具用 closure 绑定沙箱 |
| **Sandbox** | `deerflow_simple/sandbox/` | `Sandbox` 统一接口 + `LocalSandbox` 本地实现 |
| **Memory** | `deerflow_simple/memory/` | LLM 从对话抽取事实，JSON 持久化，跨轮注入 |
| **Context Engineering** | `deerflow_simple/middlewares/` | 有序的 `AgentMiddleware` 链 |
| **LangSmith** | `deerflow_simple/tracing.py` | 由 langchain 内置 env 驱动自动集成 |
| **MCP Server** | `deerflow_simple/mcp/` | `MultiServerMCPClient` 发现 stdio 工具 |
| **Worker 协程管理** | `deerflow_simple/runs/` | `RunManager` 准入 + 后台 `run_agent` 协程消费，支持取消/串行 |
| **HTTP API** | `deerflow_simple/app/` | FastAPI 网关，把 run 的创建/等待/流式/查询/取消暴露为 REST 接口 |

## 核心架构（一句话）

```
create_agent(model, tools, middleware, system_prompt, state_schema, checkpointer)
```

一个 agent 的骨架就是这六样东西。DeerFlow 的灵魂是**那串有序的 middleware**，
它们对"一条用户消息 → 最终发给模型的请求"做层层加工：

```
DynamicContext   → 注入日期 + 长期记忆（before_agent）
DurableContext   → 捕获已加载技能 + 投影摘要/技能/委派记录（before_model + wrap_model_call）
Summarization    → 接近 token 上限时自动压缩历史（before_model）
Memory           → 运行结束后把对话入队抽取记忆（after_agent）
SystemCoalescing → 合并多条 SystemMessage 为一条前导（wrap_model_call）
```

## 目录结构

```
deerflow_simple/
├── pyproject.toml
├── README.md
├── .env.example
├── deerflow_simple/          # 框架包
│   ├── config.py             # 精简配置（单个 dataclass）
│   ├── model.py              # 模型工厂（OpenAI 兼容）
│   ├── state.py              # ThreadState（状态 schema 与 reducer）
│   ├── tracing.py            # LangSmith 集成
│   ├── agent.py              # 组装核心（model+tools+middleware+prompt）
│   ├── client.py             # 嵌入式客户端（最简入口）
│   ├── middlewares/          # Context Engineering
│   ├── memory/               # 长期记忆
│   ├── skills/               # 技能加载 + 渐进检索
│   ├── sandbox/              # 沙箱接口 + 本地实现
│   ├── subagents/            # 子代理委派
│   ├── runs/                 # worker 协程管理（RunManager + run_agent）
│   ├── app/                  # FastAPI 网关（run 的 REST 接口）
│   └── mcp/                  # MCP 集成
└── examples/                 # 9 个渐进式示例 + 示例技能
```

## 安装

```bash
cd deerflow_simple
uv sync
```

基础依赖：`langchain`、`langgraph`、`langchain-openai`、`langchain-mcp-adapters`、`langsmith`（Python ≥ 3.12）。

HTTP API 需要额外安装 server 依赖：

```bash
uv sync --extra server   # 引入 fastapi + uvicorn
```

SQLite checkpointer 持久化需要额外安装 sqlite 依赖：

```bash
uv sync --extra sqlite   # 引入 langgraph-checkpoint-sqlite + aiosqlite（异步后端）
```

## 配置模型

用环境变量（复制 `.env.example` 后填写）：

```bash
export DS_MODEL=deepseek-chat          # 实际模型 id
export DS_BASE_URL=https://api.deepseek.com
export DS_API_KEY=sk-xxxx
# 或直接填 OpenAI 标准变量
export OPENAI_API_KEY=sk-xxxx
```

任何 OpenAI 兼容的端点都可以（OpenAI / DeepSeek / vLLM / Ollama 的 `/v1` 等）。

## 快速开始

```bash
cd deerflow_simple

# 01 纯问答
python examples/01_qa.py

# 02 沙箱工具（bash / read_file / write_file / ls）
python examples/02_tools_sandbox.py

# 03 技能渐进加载
python examples/03_skills.py

# 04 长期记忆（跨轮记住事实）
python examples/04_memory.py

# 05 子代理委派（task 工具）
python examples/05_subagents.py

# 06 MCP 工具（需要本机有 npx）
python examples/06_mcp.py

# 07 worker 协程管理（后台提交 / 取消 / 同线程串行）
python examples/07_runs.py

# 08 checkpointer（memory / sqlite 对话状态持久化）
python examples/08_checkpointer.py

# 09 业务工具注入（extra_tools 挂载工作流工具）
python examples/09_extra_tools.py
```

启动 HTTP API（需要先 `uv sync --extra server`）：

```bash
uvicorn deerflow_simple.app.app:app --reload
# 交互式文档：http://127.0.0.1:8000/docs
```

接口一览：

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/runs` | 创建后台 run，立即返回 |
| POST | `/api/runs/wait` | 创建 run 并阻塞等待结果 |
| POST | `/api/runs/stream` | 创建 run 并 SSE 流式返回 |
| GET | `/api/threads/{thread_id}/runs` | 列出线程的全部 run |
| GET | `/api/threads/{thread_id}/runs/{run_id}` | 查询单个 run |
| POST | `/api/threads/{thread_id}/runs/{run_id}/cancel` | 取消一个 run |

也可以编程式使用：

```python
from deerflow_simple import SimpleClient, SimpleConfig

client = SimpleClient(SimpleConfig(sandbox_enabled=True, memory_enabled=True))
print(client.chat("你好", thread_id="t1"))
```

## 开启 LangSmith

```bash
export LANGSMITH_TRACING=true
export LANGSMITH_API_KEY=lsv2_xxxx
export LANGSMITH_PROJECT=deerflow-simple
```

再跑任意示例，整条 agent 运行就会作为一个 trace 上报到 LangSmith（一个 graph 运行 =
一个 trace，各 model / tool / node 为 child span）。

## 与原 DeerFlow 的差异（砍了什么）

| 原 DeerFlow | 本仓库 |
|-------------|--------|
| Gateway REST + IM 渠道（Feishu/Slack/...） | 仅嵌入式客户端 |
| Sandbox 多 provider（AIO/E2B/Boxlite/Tenki） | 仅 `LocalSandbox` |
| Memory 多后端（deermem/mem0/openviking/honcho） | 仅 JSON 文件事实存储 |
| authz / 多实例 / scheduled tasks / batch 等企业级功能 | 全部移除 |
| checkpoint delta mode / run events / SQL 迁移 | 可配置 checkpointer（`memory` / `sqlite`） |

> **安全提示**：`LocalSandbox` 不是安全边界，子进程以宿主权限运行。真实隔离需要
> Docker（对应 DeerFlow 的 `AioSandboxProvider`）。本项目仅用于学习演示。
