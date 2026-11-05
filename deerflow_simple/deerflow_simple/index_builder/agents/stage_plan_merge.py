"""StagePlanMergeAgent —— prescan 阶段「阶段计划合并」Agent 装配。

对应设计文档《04-prompt_第一阶段粗读.md》§3 + 《03-核心图设计_索引生成.md》§2.2 N3。

**对文档的两处纠正**：

1. 04-prompt §3.2 原让 Agent 用 ``write_file`` 直接落盘 ``stage-plan.json``，但这与
   《03-核心图设计》§5.10「写入全走确定性路径，ReAct 只给只读工具」冲突。按后者为准：
   本 Agent 只产出**结构化 JSON**（不写文件），由 prescan 节点解析后确定性落盘。
2. 04-prompt §1.2/§3 原设计「全书一次、单次 LLM、输入 N 份 VolReport」。这对长篇小说
   （如 14 卷 2076 章）不成立——N 份 VolReport 全量塞进单次 merge 会超出模型上下文窗口，
   导致模型静默返回空。改为**滚动增量合并**：每次只喂「已合并骨架 + 单卷 VolReport」，
   逐卷滚动 N 次，每次输入规模稳定可控。

- 滚动增量：N 卷 = N 次串行 merge 调用，每次输入「cur_skeleton + 单卷 vol_report」。
- 工具：``list_dir`` / ``read_file``（read_file 仅跨卷衔接回查，调用预算 ≤3）。
- 输出：合并后的骨架 JSON（仅 stages / character_candidates / merge_notes 三字段，
  其余 schema 元数据与 scanned_ranges 由节点函数确定性补全）。
"""

from __future__ import annotations

from langchain.agents import create_agent

from deerflow_simple.config import SimpleConfig
from deerflow_simple.index_builder.tools.source import build_source_tools
from deerflow_simple.model import create_chat_model

# 模块级 System Prompt（来自 04-prompt §3.2，滚动增量合并模式 + 去除 write_file 落盘要求）
STAGE_PLAN_MERGE_SYSTEM = """你是「阶段计划合并员」。你以**滚动增量**方式合并全书阶段骨架：每次拿到「已合并的前若干卷骨架 + 单卷扫读报告」，产出更新后的骨架，逐卷滚动，最后一卷才做全书收口。

## 你的工作原则

1. **你是合并员，不是重新扫读员。**
   - 输入已包含每卷的 stage_candidates、人物提及、跨卷衔接提示
   - 你的工作是**跨卷对齐、合并同类项、消解边界歧义**
   - 只在必须判断「当前卷卷首 vs 上一卷卷尾应否合并为同一阶段」时才用 read_file 回查原文

2. **阶段切分最终准则**（与 ScanVol 一致）
   - ① 主要目标变化    ② 核心冲突收束    ③ 长期场景转换
   - 普通战斗/对话/短暂换场景不独立成阶段

3. **增量合并策略（核心）**
   - 重点判断「cur_skeleton 的最后一个 stage」与「当前卷第一个 stage_candidate」是否在**目标和冲突**上延续：
     - 延续 → 把当前卷第一个 candidate **并入**最后一个 stage（扩展 chapter_ranges、追加 volume_ids）
     - 不延续 → 开新 stage
   - 当前卷内部的多个 stage_candidate 依次处理：先判断是否并入上一 stage，否则开新 stage
   - 若当前卷多个 candidate 很零碎（如 3–5 个小候选），**向上合并**到更粗粒度，避免阶段过碎
   - 全书最终阶段数量建议 **5–15 个**；超过 20 个请检查是否过度拆分

4. **character_candidates 增量合并**
   - 当前卷 character_mentions 与 cur_skeleton.character_candidates **跨卷同名合并**（chapter_ranges 合并为连续/非连续区间），新名字追加
   - **不**跨名合并（即便疑似化名/绰号），精读阶段才消解
   - 一次性/路人角色（仅在一卷出现 ≤2 章）过滤掉
   - 建议最终 character_candidates 控制在 **30–100 个**

5. **收口硬校验（仅 is_last=true 时执行）**
   - 所有 stages 的 chapter_ranges **连续、无重叠、无遗漏**
   - 第一个 stage 从章节 1 开始，最后一个 stage 到 total_chapters 结束
   - 每个 stage 必填 `boundary_reason`
   - 非末卷（is_last=false）**不做**全书连续性校验（骨架尚未完整），只保证「已合并部分」连续、无重叠

## 目录结构与工具

小说根目录（novel_root）下关键结构：
- `manifest.json`：小说元信息（novel_id、title、author、source_version）
- `source/index.json`：全书卷清单（entries[].chapter_ranges + target.path）
- `source/vol-XXX/index.json`：单卷章节清单（chapters[].chapter_order、title、path）
- `source/vol-XXX/ch-NNNNNN.txt`：章节原文

可用工具：
- `list_dir(rel_path)`：列出目录内容
- `read_file(rel_path)`：读任意文件原始内容（JSON 返回原文自行解析；txt 返回正文）

**工具调用约定**：
1. `read_file` 仅用于跨卷衔接存疑时回查原文，总调用 ≤ 3 次，默认不调用
2. 你**不写文件**，只输出 JSON（由下游节点确定性落盘）
3. 你**不负责计算** `scanned_ranges` / `novel_id` / `source_version` / `status` 等元数据
   （这些由下游节点根据各卷 scanned_chapters 与 novel_meta 确定性补全）

## 输出格式（严格 JSON，仅三字段）

你每次输出「合并后的骨架」，只含三个字段，schema 元数据由下游节点统一补全：

```json
{
  "stages": [
    {
      "id": "stage-001",
      "title": "初识与入门",
      "volume_ids": ["vol-001", "vol-002"],
      "chapter_ranges": [{"start": 1, "end": 84}],
      "boundary_reason": "..."
    }
  ],
  "character_candidates": [
    {"name": "林舟", "chapter_ranges": [{"start": 1, "end": 2500}]}
  ],
  "merge_notes": [
    "vol-002 尾 + vol-003 头合并为 stage-002（目标连续：外门修炼）"
  ]
}
```

- `stages`：合并后的**完整**阶段列表（含历史 stage + 本卷新增/扩展的 stage）
- `character_candidates`：合并后的**完整**人物候选列表
- `merge_notes`：追加本卷的合并决策说明（保留历史 + 新增；若累积过长，可精简为关键决策）
- stage 的 `id` 建议 `stage-001` 起顺序编号；若本卷把两个相邻 stage 合并，需重排编号并保证顺序连续

> `merge_notes` 是本 Agent 新增的审计字段，仅用于人工审核时理解合并逻辑，不属于 §11.1 核心 schema；若与下游有兼容冲突可省略。

## 禁止事项

- ❌ 不要输出 Markdown 或任何说明性文字，只输出 JSON
- ❌ 不要修改任何 VolReport 的事实（如改章节号、改人物名）
- ❌ 不要自作主张合并化名、绰号或疑似同一人物
- ❌ 不要让 chapter_ranges 出现跳章、重叠、超过 total_chapters
- ❌ 不要预测或虚构 VolReport 中未提及的人物或情节
- ❌ 不要输出 novel_id / source_version / status / scanned_ranges 等元数据字段（由下游补全）
"""


def build_stage_plan_merge_agent(config: SimpleConfig, novel_root: str):
    """装配 StagePlanMergeAgent（滚动增量，无状态，按 novel_root 复用）。"""
    model = create_chat_model(config, temperature=0.2, max_tokens=config.index_max_tokens)
    tools = build_source_tools(novel_root)
    return create_agent(
        model=model,
        tools=tools,
        system_prompt=STAGE_PLAN_MERGE_SYSTEM,
    )


def build_stage_plan_merge_prompt(
    novel_root: str,
    novel_id: str,
    title: str,
    author: str | None,
    source_version: str,
    total_chapters: int,
    total_vols: int,
    vol_id: str,
    vol_index: int,
    cur_skeleton_json: str,
    vol_report_json: str,
    is_last: bool,
) -> str:
    """构造 StagePlanMergeAgent 的 User Prompt（滚动增量合并模式）。

    每次只喂「当前已合并骨架 cur_skeleton + 单卷 VolReport」，逐卷滚动；
    只有末卷才要求全书收口硬校验。
    """
    # 末卷额外追加收口校验指令；非末卷只要求「已合并部分连续无重叠」。
    close_step = (
        "5. 收口硬校验：全书 stages 的 chapter_ranges 连续、无重叠、无遗漏，"
        "第一个 stage 从第 1 章开始、最后一个 stage 到 total_chapters 结束\n"
    ) if is_last else ""

    return (
        f"【任务】滚动增量合并：把当前卷并入已有阶段骨架。\n\n"
        f"- novel_root: {novel_root}\n"
        f"- novel_meta:\n"
        f"  - novel_id: {novel_id}\n"
        f"  - title: {title}\n"
        f"  - author: {author}\n"
        f"  - source_version: {source_version}\n"
        f"  - total_chapters: {total_chapters}\n"
        f"  - total_vols: {total_vols}\n"
        f"- current_vol: {vol_id}（第 {vol_index}/{total_vols} 卷）\n"
        f"- is_last: {is_last}\n\n"
        f"【当前已合并骨架 cur_skeleton】\n{cur_skeleton_json}\n\n"
        f"【当前卷扫读报告 vol_report】（已剔除 scanned_chapters）\n{vol_report_json}\n\n"
        f"请执行：\n"
        f"1. 判断当前卷第一个 stage_candidate 是否延续 cur_skeleton 最后一个 stage"
        f"（延续则并入并扩展 chapter_ranges / 追加 volume_ids，否则开新 stage）\n"
        f"2. 处理当前卷其余 stage_candidate（依次判断并入上一 stage 或开新）\n"
        f"3. 增量合并 character_candidates（跨卷同名合并 chapter_ranges，过滤路人）\n"
        f"4. 追加 merge_notes\n"
        f"{close_step}"
        f"6. 输出合并后的骨架 JSON（仅 stages / character_candidates / merge_notes 三字段，无 markdown 包裹）"
    )
