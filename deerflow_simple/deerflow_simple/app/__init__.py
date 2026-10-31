"""deerflow_simple.app —— 面向 worker 协程管理机制的 HTTP API 层。

对应 DeerFlow 的 `app/gateway/`。用 FastAPI 把 `RunManager` + `run_agent`
暴露为创建 / 等待 / 流式 / 查询 / 取消 run 的 REST 接口。
"""

from deerflow_simple.app.app import create_app

__all__ = ["create_app"]
