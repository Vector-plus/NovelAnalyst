"""Skills —— 技能发现、加载、渐进式检索。

对应 DeerFlow 的 `skills/`。一个"技能"就是一个包含 `SKILL.md` 的目录，
`SKILL.md` 的 YAML frontmatter 声明 name/description，正文是指令。
"""

from deerflow_simple.skills.types import Skill

__all__ = ["Skill"]
