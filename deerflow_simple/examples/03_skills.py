"""03 技能渐进加载 —— 演示 Progressive Skill Loading。

system prompt 里只放技能索引（名字），agent 需要时先 describe_skill 再 read_file。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deerflow_simple import SimpleClient, SimpleConfig

SKILLS_DIR = str(Path(__file__).resolve().parent / "skills")

config = SimpleConfig(
    sandbox_enabled=True,
    skills_dir=SKILLS_DIR,
    skills_deferred_discovery=True,
)
client = SimpleClient(config)

print(client.chat("帮我计算 (3.14 * 2) 的平方，使用 calculator 技能。"))
