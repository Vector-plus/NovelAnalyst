"""02 沙箱工具 —— 演示 Sandbox + Skills & Tools。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deerflow_simple import SimpleClient, SimpleConfig

config = SimpleConfig(sandbox_enabled=True)
client = SimpleClient(config)

# 让 agent 用 bash 工具完成一次计算
print("== 计算 ==")
print(client.chat("用 bash 计算 123 * 456 的结果。"))

# 让 agent 用 write_file / read_file 工具处理文件
print("\n== 文件 ==")
print(client.chat("把 'hello deerflow' 写入 note.txt，然后读出来确认内容。"))
