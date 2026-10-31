"""解说词生成 —— 纯只读 ReAct Agent + SKILL.md + 7 个只读工具。

对应设计文档《03-核心图设计_解说词生成.md》v2.0：

- 1 个 NarrationAgent（create_agent 极简装配，注入 SKILL.md 全文）
- 7 个业务只读工具 + read_file/ls 基础能力
- generate_narration 工具入口（tool-as-workflow-entry，同步返回）

对外用法（挂进 lead_agent）：:

    from deerflow_simple.narration import build_generate_narration_tool
    gen_tool = build_generate_narration_tool(config, skills_dir="examples/skills")
    client = SimpleClient(config, extra_tools=[gen_tool])
"""

from deerflow_simple.narration.agent import build_narration_agent
from deerflow_simple.narration.generate_narration import (
    build_generate_narration_tool,
    resolve_novel_root,
)
from deerflow_simple.narration.names import resolve_name_exact, resolve_name_fuzzy
from deerflow_simple.narration.read_only import ReadOnlyFs
from deerflow_simple.narration.tools import (
    build_narration_tools,
    build_skill_reference_tool,
)

__all__ = [
    "ReadOnlyFs",
    "build_narration_agent",
    "build_narration_tools",
    "build_skill_reference_tool",
    "build_generate_narration_tool",
    "resolve_novel_root",
    "resolve_name_exact",
    "resolve_name_fuzzy",
]
