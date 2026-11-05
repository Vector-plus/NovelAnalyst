"""精简配置系统。

用单个 dataclass 取代 DeerFlow 庞大的 AppConfig 体系。所有字段都有默认值，
可通过环境变量或直接构造覆盖。这是 M3 阶段"用简单 dataclass 重写 config"的落地。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _load_dotenv() -> None:
    """极简 .env 加载器（不依赖 python-dotenv）。

    从运行目录或项目根读取 .env，把 KEY=VALUE 注入 os.environ（不覆盖已存在的变量）。
    这样无论用 `uv run` 还是直接 `python`，配置都能读到 key，不依赖 uv 的 .env 行为。
    """
    candidates = [
        Path(".env"),                                     # 运行目录
        Path(__file__).resolve().parent.parent / ".env",  # deerflow_simple 根目录
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


_load_dotenv()

# 项目根目录：config.py 所在包（deerflow_simple/）的上两级，即 deerflow_simple/ 目录。
# 作为所有「相对路径」配置的稳定锚点，消除 cwd 敏感问题——
# 无论 uvicorn / python 从哪个目录启动，`DS_HOME=.deerflow_simple` 这类相对路径
# 都锚定到本项目根，而不是进程的当前工作目录（否则数据目录会错位）。
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _resolve_path(raw: str | Path) -> Path:
    """把配置里的路径统一锚定到项目根。

    - 绝对路径：原样返回（尊重用户显式指定的绝对位置）。
    - 相对路径：相对于 `_PROJECT_ROOT` 解析（而非 cwd），保证跨启动目录一致。
    """
    p = Path(raw)
    if not p.is_absolute():
        p = _PROJECT_ROOT / p
    return p


@dataclass
class ModelSettings:
    """单个模型的连接信息（OpenAI 兼容）。

    默认值直接从环境变量读取，这样不显式传配置时也能用
    `DS_MODEL` / `DS_BASE_URL` / `DS_API_KEY`（或 OpenAI 标准变量）生效。
    """

    # 实际模型 id，如 "deepseek-chat" / "gpt-4o-mini"
    model: str = field(default_factory=lambda: os.getenv("DS_MODEL", "deepseek-flash"))
    base_url: str | None = field(default_factory=lambda: os.getenv("DS_BASE_URL") or os.getenv("https://api.deepseek.com/v1"))
    api_key: str | None = field(default_factory=lambda: os.getenv("DS_API_KEY") or os.getenv("OPENAI_API_KEY"))
    temperature: float = 0.0


@dataclass
class SimpleConfig:
    """精简 agent 的全部配置。"""

    # ---- 模型 ----
    model: ModelSettings = field(default_factory=ModelSettings)

    # ---- 记忆（Memory）----
    memory_enabled: bool = True
    memory_storage_path: str | None = None  # None -> 默认 .deerflow_simple/memory.json
    # 最大事实数：超出后按 confidence 降序驱逐低分事实（对应 deermem 的 max_facts + confidence 驱逐）
    memory_max_facts: int = 50
    # 置信度阈值：LLM 抽取的事实 confidence 低于该值不存储（对应 fact_confidence_threshold）
    memory_confidence_threshold: float = 0.7
    # 注入裁剪：get_context 最多返回的条数（对应 max_injection_tokens 的条数化简化）
    memory_injection_max_facts: int = 20

    # ---- 技能（Skills & Tools / Progressive Skill Loading）----
    skills_dir: str | None = None  # None -> 项目内 examples/skills
    skills_deferred_discovery: bool = True  # True -> 渐进加载（<skill_index> + describe_skill）

    # ---- 沙箱（Sandbox）----
    sandbox_enabled: bool = True
    sandbox_workspace: str | None = None  # None -> 默认 .deerflow_simple/workspace

    # ---- 子代理（Sub-Agents）----
    subagents_enabled: bool = True
    subagent_max_turns: int = 20

    # ---- 上下文工程（Context Engineering / Summarization）----
    summarization_enabled: bool = True
    summarization_trigger_tokens: int = 4000  # 达到该 token 数触发自动摘要
    summarization_keep_messages: int = 8       # 保留最近 N 条消息

    # ---- MCP Server ----
    # {"server_name": {"command": "npx", "args": [...], "transport": "stdio"}}
    mcp_servers: dict[str, Any] = field(default_factory=dict)

    # ---- 系统提示 ----
    system_prompt: str | None = None  # None -> 使用内置默认

    # ---- Checkpointer（对话状态持久化）----
    checkpointer_type: str = "memory"  # memory | sqlite
    checkpointer_path: str | None = None  # sqlite 文件路径；None -> 默认 data_dir/checkpoints.db

    # ---- 小说空间（Spaces，纯后端）----
    spaces_db_path: str | None = None  # sqlite 文件路径；None -> 默认 data_dir/spaces.db

    # ---- 长任务（Tasks，索引生成等）----
    tasks_db_path: str | None = None  # sqlite 文件路径；None -> 默认 data_dir/tasks.db

    # ---- 会话（Sessions，对话会话持久化元数据）----
    session_db_path: str | None = None  # sqlite 文件路径；None -> 默认 data_dir/sessions.db

    # ---- Agent 执行（迭代上限）----
    # LangGraph 的 super-step 递归上限，防止 agent 异常死循环跑爆预算。
    # 注意：langchain 1.x 的 create_agent 已无 max_iterations 参数，agent 在「模型不再
    # 调用工具」时自然终止；此字段只作为 LangGraph 层的安全阈值（默认 9999 足够大）。
    recursion_limit: int = 9999

    # ---- lead_agent 预算（Agent Budget）----
    # lead_agent 的工具调用次数上限（任务路由 + 下发：一次解说任务通常只调 1~2 次工作流入口工具）。
    # 防止 lead_agent 失控反复探索沙箱 / 反复调用 generate_narration。
    agent_max_tool_calls: int = 100
    # lead_agent 的 token 预算上限（累计「循环增量」token：模型输出 + 工具参数 + 工具返回）。
    agent_token_budget: int = 200000

    # ---- 解说词预算（Narration Budget）----
    # 工具调用次数上限：防止 NarrationAgent 的 ReAct 死循环（一次 tool_call+tool_result 算一次）。
    narration_max_tool_calls: int = 100
    # token 预算上限：累计「循环增量」token（模型输出 + 工具参数 + 工具返回）达到该值即停止。
    # 与 SKILL.md 的 task_token_budget（默认 32000）对齐；不含固定的 system_prompt 开销。
    narration_token_budget: int = 200000

    # ---- 索引生成预算（Index Build Budget）----
    # 索引生成各子 agent（ScanVol / ChapterReAct / StageCommit / AuditAnalyze）的工具
    # 调用次数上限。软约束由各自 System Prompt 给出（如 ChapterReAct ≤20 次），此字段
    # 是 BudgetGuard 硬兜底，防止 ReAct 死循环。
    index_max_tool_calls: int = 100
    # token 预算上限：累计「循环增量」token（模型输出 + 工具参数 + 工具返回）达到即停止。
    index_token_budget: int = 200000
    # 单次模型输出的 token 上限（max_tokens，含 reasoning 模型的「思考」+ 正式 JSON）。
    # 子 agent 输出结构化 JSON，大输出场景（stage_commit 多实体 / audit 多 issue /
    # chapter_react 多 claim）单次可能上万 token；不设上限时 DeepSeek 默认仅 4096，
    # 会截断 JSON 导致 _parse_json 失败。32768 给「思考 + 正式 JSON」留足空间。
    index_max_tokens: int = 32768
    # prescan 并发扫卷数上限。公共模型服务有频率/并发限流（如 100/min），全量
    # asyncio.gather 并发扫几十卷会瞬间触发 429。用 asyncio.Semaphore 限制同时在跑的
    # 卷数，配合 429 长退避，把请求速率压到限流窗口内。默认 3（保守，可按限流额度调）。
    index_scan_concurrency: int = 3

    # ---- 解说词结果保存（Narration Result Persist）----
    # 是否在解说词生成成功后把稿件落盘到 space_root/result/ 下（见 spaces/paths.py::resolve_novel_result_path）。
    # 落盘只发生在 status=ok（含 budget_truncated 的部分成功）时；ambiguity / error 不落盘。
    narration_save_result: bool = True

    @classmethod
    def from_env(cls) -> "SimpleConfig":
        """从环境变量构建（演示用）。"""
        model = ModelSettings(
            model=os.getenv("DS_MODEL", "gpt-4o-mini"),
            base_url=os.getenv("DS_BASE_URL") or os.getenv("OPENAI_BASE_URL"),
            api_key=os.getenv("DS_API_KEY") or os.getenv("OPENAI_API_KEY"),
        )
        return cls(model=model)

    # ---- 派生路径 ----
    @property
    def data_dir(self) -> Path:
        """数据根目录。相对路径锚定到项目根（非 cwd），保证跨启动目录一致。"""
        return _resolve_path(os.getenv("DS_HOME", ".deerflow_simple"))

    @property
    def memory_path(self) -> Path:
        return _resolve_path(self.memory_storage_path) if self.memory_storage_path else self.data_dir / "memory.json"

    @property
    def workspace_path(self) -> Path:
        return _resolve_path(self.sandbox_workspace) if self.sandbox_workspace else self.data_dir / "workspace"

    @property
    def checkpointer_conn_str(self) -> str:
        """sqlite checkpointer 的连接串（文件路径或 ':memory:'）。"""
        return str(_resolve_path(self.checkpointer_path)) if self.checkpointer_path else str(self.data_dir / "checkpoints.db")

    @property
    def spaces_db(self) -> Path:
        """小说空间元数据 SQLite 文件路径。"""
        return _resolve_path(self.spaces_db_path) if self.spaces_db_path else self.data_dir / "spaces.db"

    @property
    def tasks_db(self) -> Path:
        """长任务记录 SQLite 文件路径。"""
        return _resolve_path(self.tasks_db_path) if self.tasks_db_path else self.data_dir / "tasks.db"

    @property
    def sessions_db(self) -> Path:
        """会话元数据 SQLite 文件路径。"""
        return _resolve_path(self.session_db_path) if self.session_db_path else self.data_dir / "sessions.db"