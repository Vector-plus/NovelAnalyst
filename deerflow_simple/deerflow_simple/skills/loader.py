"""技能加载器。

对应 DeerFlow 的 `skills/parser.py` + `skills/__init__.py::load_skills`。

扫描 skills 目录下所有 `SKILL.md`，解析 YAML frontmatter 的 name/description。
"""

from __future__ import annotations

import re
from pathlib import Path

from deerflow_simple.skills.types import Skill

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)
_FIELD = re.compile(r"^([a-zA-Z_]+):\s*(.*)$")


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    m = _FRONTMATTER.match(content)
    if not m:
        return {}, content
    meta: dict = {}
    for line in m.group(1).splitlines():
        fm = _FIELD.match(line)
        if fm:
            meta[fm.group(1)] = fm.group(2).strip()
    return meta, m.group(2).strip()


def load_skills(skills_dir: str | None) -> list[Skill]:
    """递归扫描目录，加载所有 SKILL.md。"""
    if not skills_dir:
        return []
    root = Path(skills_dir)
    if not root.exists():
        return []
    skills: list[Skill] = []
    for skill_md in root.rglob("SKILL.md"):
        try:
            content = skill_md.read_text(encoding="utf-8")
        except OSError:
            continue
        meta, body = _parse_frontmatter(content)
        name = meta.get("name") or skill_md.parent.name
        skills.append(
            Skill(
                name=name,
                description=meta.get("description", ""),
                path=str(skill_md),
                content=body,
            )
        )
    return skills
