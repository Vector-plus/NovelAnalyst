"""Sandbox —— 沙箱执行抽象与本地实现。

对应 DeerFlow 的 `sandbox/`。核心是 `Sandbox` 接口（execute_command / read_file /
write_file / list_dir），以及 `LocalSandbox`（本地文件系统 + 子进程）。

> 安全说明：`LocalSandbox` **不是安全边界**，子进程以宿主权限运行。DeerFlow 的生产
> 隔离靠 Docker 的 `AioSandboxProvider`。这里只保留接口 + 本地实现用于学习演示，
> 切勿把它当隔离机制使用。
"""

from deerflow_simple.sandbox.sandbox import LocalSandbox, Sandbox

__all__ = ["Sandbox", "LocalSandbox"]
