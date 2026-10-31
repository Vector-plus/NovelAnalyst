"""05 子代理 —— 演示 Sub-Agents（task 工具委派）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deerflow_simple import SimpleClient, SimpleConfig

config = SimpleConfig(
    sandbox_enabled=True,
    subagents_enabled=True,
)
client = SimpleClient(config)

print(
    client.chat(
        "请把这两个独立小任务分别委派给子代理并行完成，并汇总结果：\n"
        "1) 计算 2 的 10 次方；\n"
        "2) 用 bash 列出当前目录有哪些文件。"
    )
)
