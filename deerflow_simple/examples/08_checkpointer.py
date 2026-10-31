"""08 Checkpointer —— 演示对话状态持久化（memory / sqlite 可配置）。

M0 改造点：`SimpleConfig.checkpointer_type` 在 `memory` / `sqlite` 之间切换。

- memory：进程内 InMemorySaver（默认），进程退出即丢，同一 client 内可多轮记忆。
- sqlite：写入本地文件，跨 client 实例（等价于"进程重启"）仍可恢复多轮记忆。

用法：
    python examples/08_checkpointer.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from deerflow_simple import SimpleClient, SimpleConfig


def demo_memory() -> None:
    """memory 模式：默认行为，同一 client 内多轮记忆。"""
    print("== memory 模式（进程内） ==")
    client = SimpleClient(SimpleConfig(checkpointer_type="memory"))
    print(client.chat("我叫小明，记住这个名字。", thread_id="t1"))
    print(client.chat("我叫什么？", thread_id="t1"))  # 同 client 内可记住
    client.close()


def demo_sqlite_persist() -> None:
    """sqlite 模式：写入文件，跨 client 实例（模拟进程重启）恢复记忆。"""
    print("\n== sqlite 模式（跨实例持久化） ==")
    db_path = Path(tempfile.mkdtemp()) / "checkpoints.db"
    sqlite_config = SimpleConfig(checkpointer_type="sqlite", checkpointer_path=str(db_path))

    # 第一个 client 写入记忆后关闭（模拟进程退出）
    client1 = SimpleClient(sqlite_config)
    print(client1.chat("我叫小明，记住这个名字。", thread_id="t1"))
    client1.close()

    # 第二个 client 重新打开同一 db 文件（模拟进程重启）
    client2 = SimpleClient(sqlite_config)
    print(client2.chat("我叫什么？", thread_id="t1"))  # 应能凭 sqlite 恢复记忆
    client2.close()

    print(f"\n（checkpoint 已持久化到 {db_path}）")


if __name__ == "__main__":
    demo_memory()
    demo_sqlite_persist()
