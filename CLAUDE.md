# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

**NovelAnalyst** 是一个长篇小说「二创 Agent」系统，包含两条业务工作流：

1. **索引生成（index generation）** — 输入长篇小说原文，产出结构化索引（人物 / 事件 / 设定 / 关系 / 剧情等），长任务、有状态、大量写入。
2. **解说词生成（narration generation）** — 基于索引，按用户主题产出解说稿件，短任务、无状态、纯只读。

实现方式：在 **deer-flow**（LangGraph + Next.js 的 Agent 框架）基础上做二次开发，保留其内核骨架，承载上述业务工作流。

## 当前状态（重要）

**业务代码尚未落地。** 目前仓库处于「设计 + 内核测绘」阶段，只有：

- `design/` — 完整的设计文档（需求 / 架构 / 图设计 / prompt / 索引模板 / 脚本）。
- `deer-flow/` — vendor 进来的 deer-flow 原版（只读参考 + 未来裁剪底座）。
- `基于deer-flow的二次开发.md` — 二次开发的总计划（阶段 0–6，含内核保留清单与裁剪策略）。

计划中的业务包（`novel_flow/` / `novel_analyst/`）还没创建。动手写业务代码前，先读 `基于deer-flow的二次开发.md`，它定义了「外壳大刀砍、内核几乎不动」的裁剪原则和阶段任务。

## 仓库结构

```
NovelAnalyst/
├── deer-flow/              # vendor 的 deer-flow 原版（自带 AGENTS.md/CLAUDE.md，见下）
├── design/                 # 业务设计文档（入口：design/doc/AGENT.md）
│   └── doc/
│       ├── 01-需求定义.md / 02-架构设计.md
│       ├── 03-核心图设计_索引生成.md / 03-核心图设计_解说词生成.md
│       ├── 04-prompt_*.md  # 各阶段 prompt 工程
│       ├── novel-index-templates.md  # 索引模板规范 v2.0（核心资产，大文件）
│       └── scripts/        # 4 个确定性脚本（stdlib、零依赖）
├── 基于deer-flow的二次开发.md  # 二次开发总计划
└── README.md
```

### deer-flow 的关系

`deer-flow/` 是 vendor 进来的原版框架，其文档自成体系：`deer-flow/AGENTS.md`（顶层）、`deer-flow/backend/AGENTS.md`、`deer-flow/frontend/AGENTS.md`。**改 deer-flow 内核前先读对应 AGENTS.md，不要重复其内容到本文件。**

对 NovelAnalyst 而言，deer-flow 被分为两部分（见 `基于deer-flow的二次开发.md` §1）：

- **内核（保留）**：`deer-flow/backend/packages/harness/deerflow/`（import `deerflow.*`）——7 大机制（thread 管理、skill 按需加载、tools、sandbox、memory、context engineering、MCP）几乎全在此。
- **外壳（裁剪）**：`deer-flow/backend/app/`（Gateway + IM channels）。

## 业务架构（核心大局）

两条工作流的编排方式刻意不同——这是本项目最关键的设计决策：

### 1. 索引生成：固定 StateGraph

- **编排**：全局只有 **1 个 StateGraph**（`IndexBuildGraph`，星型路由 + `phase` 字段作状态机）。
- **8 阶段**：`entry → skeleton → prescan → review_plan(👤) → deepread → audit → review_issues(👤) → derive`。
- **分层**（L0–L4）：`lead_agent`（顶层 ReAct）→ 主图节点 → 5 个可复用 ReAct Agent → ~20 个只读 Tool → 6 个底层 Service。
- **核心约束**：只读工具与写入工具严格分离；ReAct Agent 只能用只读/查询类工具，写入类（D 类）只能由节点函数确定性路径调用，防止 LLM 幻觉乱写文件。
- **断点恢复**：三层——LangGraph checkpoint（节点级）→ Ledger 四态状态机（章级，**权威事实源**）→ 文件系统 + sha256 CAS（文件级兜底）。

详见 `design/doc/03-核心图设计_索引生成.md`。

### 2. 解说词生成：灵活 Skill + 单 ReAct Agent

- **编排**：**1 个 ReAct Agent + 1 个 SKILL.md + ~7 个只读工具**，无 StateGraph、无多 Agent、无复杂 State。
- **核心资产**：`SKILL.md`（`design/doc/other/novel-narration-generator/SKILL.md`）承载全部解说方法论（六类任务、下钻顺序、充分性判据、证据分级、边界）。
- **三条确定性护栏**（绝不交 LLM 裁决）：名字消歧、覆盖预检、预算守护，内嵌为工具逻辑。
- **对外对称**：与索引生成一致，lead_agent 通过 `generate_narration` 工具触发，不感知内部是 Graph 还是 ReAct。

详见 `design/doc/03-核心图设计_解说词生成.md`。

### 一句话原则

> 用 Graph 表达阶段，用 ReAct 表达决策，用 Python 表达控制流；短任务用 skill，长任务用 Graph。

## 设计文档索引

设计文档导航见 `design/doc/AGENT.md`（含各文档用途与推荐阅读顺序）。其中核心资产：

- `design/doc/novel-index-templates.md` — 索引目录结构 / 账本 / 分片 / 校验规范 v2.0（索引生成的契约基础）。
- `design/doc/03-核心图设计_*.md` — 两条工作流的权威设计。
- `design/doc/04-prompt_*.md` — 各阶段 prompt。

## 命令

### 确定性脚本（design/doc/scripts/）

四个脚本均 Python 3 标准库、零第三方依赖，按顺序使用：

```bash
# 1. 切块：原文 → source/ 清单与单章 txt
python3 design/doc/scripts/chunk_novel.py --input xianni.txt --novel-root novel \
    --novel-id xianni --source-version source-v1 --title 仙逆 --author 耳根

# 2. 骨架：生成 manifest / 导航 / 空主题索引 / ledger / quality
python3 design/doc/scripts/init_skeleton.py --novel-root novel --novel-id xianni \
    --title 仙逆 --author 耳根 --language zh-CN --source-version source-v1 --total-chapters 10

# 3. 分片：计算章节导航 / 覆盖 / 问题分片范围
python3 design/doc/scripts/shard_chapters.py --novel-root novel --novel-id xianni --total 10 --size 50 --source-version source-v1

# 4. 校验：结构 / FileMeta / 路径安全 / 章节范围校验，退出码 0/1
python3 design/doc/scripts/validate_index.py --root novel --novel-id xianni --source-version source-v1
```

### deer-flow 相关命令

deer-flow 自身的构建 / 测试 / lint 命令（`make dev`、`make test`、`pnpm check` 等）见 `deer-flow/AGENTS.md` 与 `deer-flow/backend/AGENTS.md`、`deer-flow/frontend/AGENTS.md`，不要在本文件重复。


