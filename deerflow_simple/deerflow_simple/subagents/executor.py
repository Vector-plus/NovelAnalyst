"""SubagentExecutor —— 子代理执行器（极简版）。

对应 DeerFlow 的 `subagents/executor.py`。每个子任务编译一个一次性子代理 graph
（无 checkpointer，因为子代理是一次性的），执行后返回最终文本。

简化点：不做并发槽位、不做超时/取消、不隔离 event loop。
"""

from __future__ import annotations

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage

from deerflow_simple.config import SimpleConfig

_SUBAGENT_SYSTEM_PROMPT = (
    "你是一个通用子代理，负责完成主代理委派给你的独立子任务。"
    "你可以使用沙箱工具（bash / read_file / write_file / ls）来完成工作。"
    "完成后请给出简洁、完整的结果，不要多问。"
)


class SubagentExecutor:
    def __init__(self, config: SimpleConfig, sandbox_tools: list):
        self._config = config
        self._tools = sandbox_tools  # 子代理共享沙箱工具（对应 deer-flow 的 general-purpose）

    def execute(self, task: str) -> str:
        from deerflow_simple.model import create_chat_model

        model = create_chat_model(self._config)
        graph = create_agent(
            model=model,
            tools=self._tools,
            system_prompt=_SUBAGENT_SYSTEM_PROMPT,
        )
        result = graph.invoke(
            {"messages": [HumanMessage(content=task)]},
            config={"recursion_limit": self._config.recursion_limit},
        )
        last = result["messages"][-1]
        return last.content if isinstance(last.content, str) else str(last.content)
