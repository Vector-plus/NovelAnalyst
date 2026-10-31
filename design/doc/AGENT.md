# design 目录索引

> 本文档是 `design/` 目录的导航索引，帮助快速定位设计文档、模板、脚本与参考资料。
> 项目定位：长篇小说「解析索引生成」+「解说词生成」双工作流的 Agent 系统设计。

## 目录结构

```
design/
├── doc/                                  # 设计文档主目录
│   ├── 01-需求定义.md                    # 需求、场景边界、persona、成功指标
│   ├── 02-架构设计.md                    # Agent 架构选型、模型选型、技术栈
│   ├── 03-核心图设计_索引生成.md         # 索引生成 Graph（StateGraph 设计）
│   ├── 03-核心图设计_解说词生成.md       # 解说词生成（灵活 Skill 版）
│   ├── 04-prompt_审查.md                 # N6 audit 节点 Prompt 工程
│   ├── 04-prompt_第一阶段粗读.md         # 粗读阶段 Prompt 工程
│   ├── 04-prompt_第二阶段精读.md         # 精读阶段 Prompt 工程
│   ├── novel-index-templates.md          # 索引模板规范 v2.0（核心资产）
│   ├── other/                            # 参考资料与附属文档
│   └── scripts/                          # 索引生成配套脚本
└── (本文件 AGENT.md)                     # 目录索引
```

## 一、主设计文档（doc/）

| 文件 | 说明 | 关键内容 |
| --- | --- | --- |
| [01-需求定义.md](01-需求定义.md) | 需求与边界定义 | 业务场景、用户画像、能力清单、persona 模板、成功指标体系 |
| [02-架构设计.md](02-架构设计.md) | 整体架构设计 | Pure ReAct 架构（主 agent + 两工作流工具）、模型选型、技术栈 |
| [03-核心图设计_索引生成.md](03-核心图设计_索引生成.md) | 索引生成 Graph | 唯一 StateGraph（8 阶段）、State 定义、中断恢复、工具清单 |
| [03-核心图设计_解说词生成.md](03-核心图设计_解说词生成.md) | 解说词生成设计 | 灵活 Skill 版（v2.0 重置），单 ReAct Agent + 只读工具 |
| [04-prompt_审查.md](04-prompt_审查.md) | 审查节点 Prompt | N6 `audit` 节点 `AuditAnalyzeReActAgent` 的审查 Prompt 模板 |
| [04-prompt_第一阶段粗读.md](04-prompt_第一阶段粗读.md) | 粗读阶段 Prompt | 第一阶段 prescan 粗读提示词设计 |
| [04-prompt_第二阶段精读.md](04-prompt_第二阶段精读.md) | 精读阶段 Prompt | 第二阶段 deepread 精读提示词设计 |
| [04-prompt_解说任务优化.md](04-prompt_解说任务优化.md) | 解说任务优化 Prompt | 解说任务的优化/改写提示词 |
| [04-prompt_解说任务核查.md](04-prompt_解说任务核查.md) | 解说任务核查 Prompt | 解说任务的核查/校验提示词 |
| [novel-index-templates.md](novel-index-templates.md) | 索引模板规范 v2.0 | 核心资产：索引目录结构、账本、分片、校验规范（大文件） |

## 二、附属文档（doc/other/）

| 文件/目录 | 说明 |
| --- | --- |
| [other/agent架构选型方法.md](other/agent架构选型方法.md) | Agent 编排方案决策框架（五步法 + 案例分析） |
| [other/persona_prompt.md](other/persona_prompt.md) | Agent persona 系统提示词模板 |
| [other/最终指标.md](other/最终指标.md) | 成功指标最终定义（任务成功率、满意度、成本上限） |
| [other/需求.md](other/需求.md) | 需求补充说明 |
| [other/test.md](other/test.md) | 测试/验证相关笔记 |
| [other/novel-index-creator.zip](other/novel-index-creator.zip) | 索引生成 skill 打包 |
| [other/novel-narration-generator.zip](other/novel-narration-generator.zip) | 解说词生成 skill 打包 |
| [other/novel-narration-generator/](other/novel-narration-generator/) | 解说词生成 skill 源码（SKILL.md + examples + references） |

### other/novel-narration-generator/ 子结构

- `SKILL.md`：解说词生成 skill 主说明
- `examples/`：5 类解说示例（章节/人物传记/势力/体系设定/感情线）
- `references/`：证据边界、检索手册、结构模板、5 类风格指南

## 三、配套脚本（doc/scripts/）

| 脚本 | 功能 |
| --- | --- |
| [scripts/init_skeleton.py](scripts/init_skeleton.py) | 初始化索引骨架 |
| [scripts/chunk_novel.py](scripts/chunk_novel.py) | 小说原文切块 |
| [scripts/shard_chapters.py](scripts/shard_chapters.py) | 章节分片 |
| [scripts/validate_index.py](scripts/validate_index.py) | 索引校验 |

## 四、阅读顺序建议

1. **了解全貌**：`01-需求定义` → `02-架构设计` → `other/agent架构选型方法`
2. **索引生成链路**：`03-核心图设计_索引生成` → `04-prompt_*` 各阶段 → `novel-index-templates` → `scripts/`
3. **解说词生成链路**：`03-核心图设计_解说词生成` → `other/novel-narration-generator/SKILL.md` + `references/`
