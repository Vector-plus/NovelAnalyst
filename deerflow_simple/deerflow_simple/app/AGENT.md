# App 层决策记录

## 路由挂载方式（避免循环导入）

- **自带路由放 `app/routers/`**：如 `runs.py`，通过 `app/routers/__init__.py` 聚合导出。
- **业务模块自带路由直接挂载**：如小说空间的 `spaces/router.py`（在 `deerflow_simple/spaces/`
  下，不在 `app/routers/` 下），在 `app/app.py::create_app` 里用
  `from deerflow_simple.spaces.router import router as spaces_router` 直接导入并
  `include_router`，**不要**写成 `from deerflow_simple.app.routers import spaces`。
  后者会让 Python 去 `app/routers/` 找不存在的 `spaces` 子模块，触发
  `cannot import name 'spaces' from partially initialized module` 循环导入。

如果有重要的系统决策更新需要同步更新本文件