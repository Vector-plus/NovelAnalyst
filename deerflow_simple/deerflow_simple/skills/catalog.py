"""SkillCatalog + describe_skill 工具（Progressive Skill Loading）。

对应 DeerFlow 的 `skills/catalog.py` + `skills/describe.py`。

渐进加载的核心：system prompt 里只放技能**名字索引**（`<skill_index>`），不放大段
正文，保持 prefix-cache 友好。agent 需要某个技能时，先调 `describe_skill` 拿描述，
再调 `read_file` 读 `SKILL.md` 正文。这样只有被用到的技能才消耗上下文。
"""

from __future__ import annotations

from langchain_core.tools import tool

from deerflow_simple.skills.types import Skill


class SkillCatalog:
    """技能目录：按名字查询。"""

    def __init__(self, skills: list[Skill]):
        self._skills = {s.name: s for s in skills}

    @property
    def names(self) -> list[str]:
        return list(self._skills.keys())

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def describe(self, name: str) -> str:
        skill = self._skills.get(name)
        if skill is None:
            return f"未找到技能 {name}"
        return f"技能：{skill.name}\n描述：{skill.description}"


def build_describe_skill_tool(catalog: SkillCatalog):
    @tool
    def describe_skill(name: str) -> str:
        """查询某个技能的详细信息（描述）。当你看到技能索引里有相关技能时，先调用它了解详情。"""
        return catalog.describe(name)

    return describe_skill
