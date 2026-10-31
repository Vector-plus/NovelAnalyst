"""04 记忆 —— 演示 Memory（事实抽取 + 跨轮注入）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deerflow_simple import SimpleClient, SimpleConfig

config = SimpleConfig(memory_enabled=True)
client = SimpleClient(config)

# 同一 thread_id 保持同一会话，记忆跨轮保留
print("== 第一轮：告诉它偏好 ==")
print(client.chat("我叫小明，我最喜欢的颜色是蓝色，我在学 Python。", thread_id="mem"))

print("\n== 第二轮：验证记忆被注入 ==")
print(client.chat("我最喜欢的颜色是什么？我叫什么？", thread_id="mem"))
