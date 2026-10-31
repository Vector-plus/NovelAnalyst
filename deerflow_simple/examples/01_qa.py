"""01 纯问答 —— 最简 agent，全部功能关闭。"""

import sys

from deerflow_simple import SimpleClient, SimpleConfig

# Windows 控制台默认 GBK，打印含 emoji 的 AI 回复会抛 UnicodeEncodeError；强制 UTF-8 输出
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

config = SimpleConfig(
    sandbox_enabled=True,
    # memory_enabled=True,
    subagents_enabled=False,
    summarization_enabled=False,
    # skills_dir='examples/skills'
)
client = SimpleClient(config)

# print(client.chat("你的名字叫wickfu，请记住"))
print(client.chat("你是谁"))
# client.chat("找一首李白关于爱情的古诗，写到`love.md`中")
# print(client.chat("你有哪些skill"))
