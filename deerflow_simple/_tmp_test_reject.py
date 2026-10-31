"""临时验证：在真实事件循环里验证 app 层 run_manager 的 reject 语义。"""

import asyncio

from deerflow_simple.app.app import create_app
from deerflow_simple.config import SimpleConfig
from deerflow_simple.runs import ConflictError, submit_run


async def main() -> None:
    config = SimpleConfig(
        sandbox_enabled=False,
        subagents_enabled=False,
        summarization_enabled=False,
        memory_enabled=False,
    )
    app = create_app(config)
    manager = app.state.run_manager
    graph = app.state.graph

    # 第一个 run 提交后保持 pending（不等它完成）
    rid1 = await submit_run(manager, graph, "任务A", "t2")
    print("第一个 run:", rid1[:8], "status:", manager.get(rid1).status.value)

    # 立即提交第二个（同线程），应抛 ConflictError
    try:
        await submit_run(manager, graph, "任务B", "t2")
        print("FAIL: 未拒绝并发 run")
    except ConflictError as exc:
        print("reject 冲突正确拒绝:", exc)

    # 用 interrupt 策略则应成功并中断旧 run
    rid2 = await submit_run(manager, graph, "任务C", "t2", multitask_strategy="interrupt")
    print("interrupt 策略新 run:", rid2[:8], "status:", manager.get(rid2).status.value)
    print("旧 run 状态:", manager.get(rid1).status.value)


asyncio.run(main())
print("REJECT SEMANTICS OK")
