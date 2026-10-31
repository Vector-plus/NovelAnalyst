"""Skill 类型定义。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Skill:
    """一个技能：名字 + 描述 + 正文。"""

    name: str
    description: str
    path: str
    content: str = ""

    @property
    def body(self) -> str:
        return self.content
