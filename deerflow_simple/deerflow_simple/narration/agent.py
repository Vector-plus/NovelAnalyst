"""NarrationAgent 装配 —— 解说词 ReAct Agent（无状态、一次性）。

对应设计文档《03-核心图设计_解说词生成.md》§2：1 个 ReAct Agent + 1 个 SKILL.md + ~7 个
只读工具，无 StateGraph、无多 Agent、无 checkpoint。

关键设计（复用「原语」而非「大而全装配」）：
- 复用 `langchain.agents.create_agent` 原语 + `create_chat_model` + `load_skills`。
- **不复用** `build_agent`：解说词不需要 middleware 链、memory、sandbox 全套、checkpointer。
- `system_prompt` 直接注入 `novel-narration-generator` SKILL.md 全文（唯一身份 + 宪法），
  不走渐进加载（它只有唯一必用的 skill，渐进加载只会平白多两次工具调用）。
- 工具只给 7 个业务只读工具 + read_file/ls，绝不含 write_file/bash。
"""

from __future__ import annotations

from pathlib import Path

from langchain.agents import create_agent

from deerflow_simple.config import SimpleConfig
from deerflow_simple.model import create_chat_model
from deerflow_simple.narration.tools import (
    build_narration_tools,
    build_skill_reference_tool,
)
from deerflow_simple.skills.loader import load_skills

# 目标 skill 名（与 SKILL.md frontmatter 的 name 一致）
NARRATION_SKILL_NAME = "novel-narration-generator"


def _default_skills_dir() -> Path:
    """默认 skills_dir：项目内 examples/skills。"""
    return Path(__file__).resolve().parent.parent.parent / "examples" / "skills"


def build_narration_agent(
    config: SimpleConfig,
    novel_root: str,
    skills_dir: str | None = None,
):
    """装配解说词 NarrationAgent（编译好的 graph）。

    Args:
        config: 精简配置（取 model）。
        novel_root: 索引根路径（如 xianni_test/novel/），锚定只读工具。
        skills_dir: 技能目录；None 时用 config.skills_dir 或默认 examples/skills。
    """
    model = create_chat_model(config, temperature=0.5)

    # 定位并加载 novel-narration-generator skill
    resolved_skills_dir = skills_dir or config.skills_dir or str(_default_skills_dir())
    skills = load_skills(resolved_skills_dir)
    skill = next((s for s in skills if s.name == NARRATION_SKILL_NAME), None)
    if skill is None:
        raise ValueError(
            f"未找到技能 {NARRATION_SKILL_NAME}，请确认 skills_dir 正确：{resolved_skills_dir}"
        )

    # 只读工具集（7 个业务工具 + read_file/ls）
    tools = build_narration_tools(novel_root, config)
    # 追加「读 skill 资源」工具：让 Agent 能按需加载 references/style-guide-*.md 等
    # （SKILL.md 正文引用这些方法论文档，但它们不在 novel_root 内，需单独锚定 skill 目录）
    # build_skill_reference_tool 返回两个工具：read_skill_reference + list_skill_references
    skill_dir = str(Path(skill.path).parent)
    tools.extend(build_skill_reference_tool(skill_dir))

    # 极简装配：不传 middleware / state_schema / checkpointer
    return create_agent(
        model=model,
        tools=tools,
        system_prompt=skill.body,  # SKILL.md 全文即身份
    )
