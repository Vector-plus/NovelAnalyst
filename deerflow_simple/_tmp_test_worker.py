import asyncio

from langchain_core.messages import AIMessage

from deerflow_simple.runs import ConflictError, RunManager, RunStatus, submit_run, wait_run


class FakeGraph:
    def __init__(self, delay: float = 0.0):
        self.delay = delay

    def astream(self, input_payload, config=None, stream_mode=None):
        async def gen():
            if self.delay:
                await asyncio.sleep(self.delay)
            yield {"messages": []}
            yield {"messages": [AIMessage(content="hello world")]}
        return gen()


async def main() -> None:
    mgr = RunManager()
    graph = FakeGraph()

    # 1. 提交 + 等待
    rid = await submit_run(mgr, graph, "hi", "t1")
    print("submit status:", mgr.get(rid).status.value)
    result = await wait_run(mgr, rid)
    print("wait result:", result, "| status:", mgr.get(rid).status.value)

    # 2. reject 冲突
    rid2 = await submit_run(mgr, graph, "hi2", "t1")
    try:
        await submit_run(mgr, graph, "hi3", "t1")
        print("FAIL: should have raised ConflictError")
    except ConflictError:
        print("reject conflict: ok")
    await wait_run(mgr, rid2)

    # 3. 取消（慢 graph）
    slow = FakeGraph(delay=0.3)
    rid3 = await submit_run(mgr, slow, "hi4", "t2")
    print("before cancel status:", mgr.get(rid3).status.value)
    mgr.cancel(rid3)
    await asyncio.sleep(0.4)
    print("after cancel status:", mgr.get(rid3).status.value)

    # 4. 同线程串行：两个 run 都排队依次完成
    rid_a = await submit_run(mgr, graph, "a", "t3", multitask_strategy="interrupt")
    rid_b = await submit_run(mgr, graph, "b", "t3", multitask_strategy="interrupt")
    print("rid_a status after interrupt-admit:", mgr.get(rid_a).status.value)
    print("rid_b result:", await wait_run(mgr, rid_b))


asyncio.run(main())
print("ALL OK")
