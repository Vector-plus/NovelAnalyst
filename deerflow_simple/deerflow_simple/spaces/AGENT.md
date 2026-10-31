# Spaces（小说空间）模块决策记录

## 定位
- 纯后端模块，**无 LLM 参与**。承载产品化的两个基础能力：小说空间（元数据 + 沙箱目录）
  的列表/创建/查询/更新/删除，以及空间内原文的增删改查。
- 对应需求：页面「创建小说空间」→ 后端生成唯一 id 存库 + 建沙箱环境；空间内后续所有
  操作都在该沙箱目录下完成。

## 关键决策
1. **id 即 novel_id**：`NovelSpace.id`（uuid4 hex）就是解说词模块使用的 `novel_id`，
   小说空间根（space root）为 `config.workspace_path / id`。
2. **路径分两层（关键，避免工具找不到路径）**：
   - **space root** = `config.workspace_path / id`：存原文 `source/novel.txt`（spaces 模块管理）。
   - **index root** = `config.workspace_path / id / novel`：存 `manifest.json` 与各主题索引
     （novel-index-creator 生成，`INDEX_DIR = "novel"`）。
   - narration 解说词锚定 **index root**，不是 space root；spaces 原文 CRUD 锚定 space root。
     二者不可混用，否则 `load_manifest` 会找不到 `manifest.json`。
3. **路径映射单一来源**：`paths.resolve_novel_path` 是 id→space root 的**唯一**实现；
   `paths.resolve_novel_index_path` 是 id→index root 的**唯一**实现（内部复用
   `resolve_novel_path` + `INDEX_DIR`）。narration 的 `resolve_novel_root` 复用
   `resolve_novel_index_path`（只额外做存在性校验）。
4. **元数据用 stdlib sqlite3**：字段少、查询简单，不引 ORM；数据库文件在
   `config.spaces_db`（默认 `.deerflow_simple/spaces.db`）。
5. **建空间原子性**：先建目录再写元数据，元数据写失败回滚删目录，避免脏状态。
6. **原文存放约定**：原文统一放 space root 的 `source/` 下，**唯一一个文件**（文件名固定为
   `SOURCE_FILE = "novel.txt"`，接口无 `path` 参数），统一以 UTF-8 落盘。索引树
   （novel-index-creator skill）应从此处读取原文。
7. **原文上传走文件上传（multipart/form-data）**：`PUT /api/spaces/{id}/source` 接收
   `UploadFile`（非 JSON content），后端用 charset-normalizer 自动探测原始编码
   （UTF-8 / GBK / GB18030 / Big5 等）并统一转 UTF-8；删为 `DELETE /api/spaces/{id}/source`、
   查为 `GET /api/spaces/{id}/source`（返回内容）。
8. **解说词结果目录（result）是多文件、平铺的 `.md`**（与 source 唯一文件不同）：
   - 路径单一来源：`paths.resolve_novel_result_path`（id → `workspace/{id}/result`，复用
     `resolve_novel_path` 防穿越）。result 是解说词**产出物写入区**，挂在 space root 下，
     与 index root（`novel/` 只读消费区）语义不同、不可混用。
   - **写接口用 JSON body**（`ResultWriteRequest.content`），而非 multipart：result 是自产的
     UTF-8 Markdown，无需编码探测（与 source 的 `UploadFile` 上传不同）。
   - CRUD 四接口（均带 `filename` 路径参数）：
     - `GET /api/spaces/{id}/result` → 列出文件名；
     - `GET /api/spaces/{id}/result/{filename}` → 读内容；
     - `PUT /api/spaces/{id}/result/{filename}` → 幂等创建/覆盖（增/改合一）；
     - `DELETE /api/spaces/{id}/result/{filename}` → 删除。
   - **filename 由用户输入，必须防穿越**（source 因固定文件名无此问题）：拒绝含 `/`、`\\` 及
     `.`/`..`/空串，且 resolve 后必须仍位于 result 目录内（见安全护栏）。

## 文件职责
| 文件 | 职责 |
|---|---|
| `paths.py` | `resolve_novel_path` id→space root 映射 + `resolve_novel_index_path` id→index root 映射 + `resolve_novel_result_path` id→result 目录映射（均防穿越，不校验存在性） |
| `models.py` | `NovelSpace` dataclass + `now_iso` |
| `store.py` | `SpaceStore` SQLite 元数据 CRUD |
| `manager.py` | `SpaceManager` 建空间（原子）+ 原文 CRUD（防穿越）+ 结果 CRUD（防穿越） |
| `schemas.py` | HTTP 请求/响应 Pydantic 模型（含 `ResultWriteRequest`） |
| `router.py` | FastAPI 路由（`/api/spaces`，含 result 四接口） |

## 安全护栏（确定性，不交给 LLM）
- `resolve_novel_path`：novel_id 解析后必须位于 workspace 内。
- `resolve_novel_index_path`：复用 `resolve_novel_path`，index root 恒为 space root 下的
  固定子目录 `novel/`，无用户输入路径，故无额外穿越面。
- `resolve_novel_result_path`：复用 `resolve_novel_path`，result 目录恒为 space root 下的
  固定子目录 `result/`，无用户输入路径，故无额外穿越面。
- 原文为唯一固定文件（`source/SOURCE_FILE`），无用户输入的路径，故无路径穿越面。
- 结果为多文件，`filename` 由用户输入，**需防穿越**：`manager._result_file_of` 拒绝含
  `/`、`\\` 及 `.`/`..`/空串的文件名，且 resolve 后必须仍位于 result 目录内（双重保险）。

## 已知待办
- 索引创建（`build_novel_index` 写工作流）、解说词对话框（`generate_narration` 只读
  工作流）是后续 LLM 参与的能力，不在本模块；本模块只提供它们的空间/原文数据底座。
- `novel_id` 会话绑定（方案 A：thread_id 前缀 → 注入工具）尚未实现，待解说对话框接入时落地。
