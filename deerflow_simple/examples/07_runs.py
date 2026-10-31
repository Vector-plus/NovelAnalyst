"""07 worker 协程管理 —— 后台提交 / 状态查询 / 取消 / 同线程串行。

对应 DeerFlow 的 `RunManager` + `run_agent` 后台 worker 机制。演示：

1. `submit` 非阻塞提交，立即拿到 run_id
2. `status` 轮询 run 生命周期状态
3. `cancel` 取消一个活跃 run
4. reject 策略下同线程并发提交会被拒绝
"""

import sys
import time

from deerflow_simple import ConflictError, SimpleClient, SimpleConfig

# Windows 控制台默认 GBK，打印含 emoji 的 AI 回复会抛 UnicodeEncodeError；强制 UTF-8 输出
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

config = SimpleConfig(
    sandbox_enabled=False,
    subagents_enabled=False,
    summarization_enabled=False,
)
client = SimpleClient(config)


def demo_submit_and_wait() -> None:
    """非阻塞提交，然后阻塞等待结果。"""
    print("\n=== 1. 后台提交 + 等待 ===")
    run_id = client.submit("用一句话介绍你自己", thread_id="t1")
    print(f"已提交 run_id={run_id[:8]}...，status={client.status(run_id)}")
    # 这里可以做别的事；wait 阻塞直到完成
    result = client.wait(run_id)
    print(f"status={client.status(run_id)}")
    print(f"结果: {result}")


def demo_cancel() -> None:
    """提交一个较长的任务后取消它。"""
    print("\n=== 2. 取消活跃 run ===")
    run_id = client.submit("写一篇 2000 字的长篇小说大纲", thread_id="t2")
    print(f"已提交 run_id={run_id[:8]}...，status={client.status(run_id)}")
    time.sleep(0.5)
    cancelled = client.cancel(run_id)
    print(f"cancel() -> {cancelled}")
    time.sleep(0.5)
    print(f"status={client.status(run_id)}（应为 interrupted）")


def demo_reject_strategy() -> None:
    """reject 策略：同线程已有活跃 run 时第二次提交被拒。"""
    print("\n=== 3. 同线程并发 reject ===")
    run_id = client.submit("从 1 数到 100", thread_id="t3")
    print(f"首个 run_id={run_id[:8]}...，status={client.status(run_id)}")
    try:
        client.submit("另一个任务", thread_id="t3")
    except ConflictError as exc:
        print(f"第二次提交被拒: {exc}")
    print("等待首个 run 完成...")
    print(f"结果: {client.wait(run_id)}")


if __name__ == "__main__":
    demo_submit_and_wait()
    demo_cancel()
    demo_reject_strategy()
