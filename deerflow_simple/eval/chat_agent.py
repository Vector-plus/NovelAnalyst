"""极简 ReAct Agent（Reasoning + Acting），用于 eval 对照实验。

与 `eval/agent.py` 的「一问一答」不同，这里把 ReAct 循环显式写出来：

    Thought -> Action + Action Input -> Observation -> ... -> Final Answer

工具调用走**纯文本协议**（不依赖模型的 function calling 能力），任何 OpenAI 兼容的
Chat 模型都能跑。对外接口与 `agent.py` 完全一致，因此 `harbor_adapter.py` 只需把
`_AGENT_PATH` 指向本文件即可直接评测：

    model            # ChatOpenAI，adapter 会读取 temperature 作为元数据
    chat(msg) -> str # 返回最终答案文本

评测环境负责把 `chat()` 的返回值写入 `/app/hello.txt`，所以本 agent 只返回答案本身，
不提供写文件工具。调试轨迹输出到 stderr，不污染 stdout。

可通过环境变量调整：
    DS_REACT_WORKSPACE   文件类工具的工作区根目录（默认 NovelAnalyst 仓库根）
    DS_REACT_MAX_STEPS   最多推理轮数（默认 6）
    DS_REACT_VERBOSE=1   打印 Thought/Action/Observation 轨迹到 stderr
"""

# pyright: reportImplicitRelativeImport=false

from __future__ import annotations

import ast
import inspect
import json
import operator
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, ClassVar

# 支持直接 `python eval/chat_agent.py` 运行（adapter 已注入过该路径时会跳过）。
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from deerflow_simple.config import SimpleConfig
from deerflow_simple.model import create_chat_model

try:
    model = create_chat_model(SimpleConfig.from_env(), temperature=0.0)
except ValueError as exc:
    model = None
    print(f"配置错误：{exc}", file=sys.stderr)


# --------------------------------------------------------------------------- #
# 文件类工具的工作区（只读 + 路径护栏）
# --------------------------------------------------------------------------- #

_WORKSPACE = Path(
    os.getenv("DS_REACT_WORKSPACE") or str(Path(__file__).resolve().parents[2])
).resolve()
_SKIP_DIRS = {
    ".git", ".venv", "node_modules", "__pycache__", ".codebuddy",
    ".deerflow_simple", "dist", "build", "frontend", "deer-flow", "jobs",
}
_TEXT_SUFFIXES = {".txt", ".md", ".json", ".jsonl", ".py", ".toml", ".csv", ".log"}
_MAX_FILE_BYTES = 1_000_000
_MAX_SCAN_FILES = 200
_MAX_OBSERVATION = 3000


def _safe_path(raw: str) -> Path:
    """把任意路径收敛到工作区内。

    Harbor 任务里常出现 `/app/hello.txt` 这类容器绝对路径，这里按「工作区内的
    相对路径」处理；`..` 逃出工作区则直接拒绝。
    """
    text = str(raw).strip().strip('"').strip("'").replace("\\", "/").lstrip("/")
    if re.match(r"^[A-Za-z]:/", text):
        text = text[3:]
    target = (_WORKSPACE / Path(text)).resolve()
    if not target.is_relative_to(_WORKSPACE):
        raise ValueError(f"路径越界：{raw!r}（只允许访问工作区 {_WORKSPACE}）")
    return target


def _read_text(path: Path) -> str:
    data = path.read_bytes()[:_MAX_FILE_BYTES]
    for encoding in ("utf-8", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(_WORKSPACE))
    except ValueError:
        return str(path)


# --------------------------------------------------------------------------- #
# 工具实现
# --------------------------------------------------------------------------- #

_BINOPS: dict[type, Callable[..., float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARYOPS: dict[type, Callable[..., float]] = {
    ast.UAdd: lambda value: +value,
    ast.USub: lambda value: -value,
}


def _eval_node(node: ast.AST) -> float:
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
    ):
        return node.value
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARYOPS:
        return _UNARYOPS[type(node.op)](_eval_node(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        left, right = _eval_node(node.left), _eval_node(node.right)
        if isinstance(node.op, ast.Pow) and (abs(right) > 100 or abs(left) > 1_000_000):
            raise ValueError("幂运算过大")
        return _BINOPS[type(node.op)](left, right)
    raise ValueError("表达式只支持数字与 + - * / // % **")


def _calculator(expression: str) -> str:
    """安全的四则/幂运算（基于 ast，不执行任意代码）。"""
    result = _eval_node(ast.parse(expression, mode="eval").body)
    return f"{expression} = {result}"


def _list_files(path: str = ".") -> str:
    """列出工作区目录下的文件与子目录。"""
    target = _safe_path(path)
    if target.is_file():
        return _relative(target)
    if not target.is_dir():
        return f"错误：目录不存在 {path!r}"
    items = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name))[:200]
    lines = [("[目录] " if p.is_dir() else "[文件] ") + _relative(p) for p in items]
    return "\n".join(lines) or "(空目录)"


def _read_file(path: str, max_chars: int = 4000) -> str:
    """读取工作区内一个文本文件（UTF-8 / GB18030 自动识别，超长截断）。"""
    target = _safe_path(path)
    if not target.is_file():
        return f"错误：文件不存在 {path!r}"
    text = _read_text(target)
    limit = max(200, min(int(max_chars), 20_000))
    if len(text) > limit:
        return text[:limit] + f"\n...(已截断，共 {len(text)} 字符)"
    return text or "(空文件)"


def _search_text(query: str, path: str = ".", max_matches: int = 8) -> str:
    """在工作区的文本文件中检索关键字，返回 `相对路径:行号: 匹配行`。"""
    needle = query.strip().lower()
    if not needle:
        return "错误：query 不能为空"
    target = _safe_path(path)
    if not target.exists():
        return f"错误：路径不存在 {path!r}"

    files = [target] if target.is_file() else []
    if target.is_dir():
        for current, dirnames, filenames in os.walk(target):
            dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
            files.extend(Path(current) / name for name in sorted(filenames))
            if len(files) >= _MAX_SCAN_FILES:
                break

    cap = max(1, min(int(max_matches), 30))
    hits: list[str] = []
    scanned = 0
    for file in files:
        if scanned >= _MAX_SCAN_FILES or len(hits) >= cap:
            break
        if file.suffix.lower() not in _TEXT_SUFFIXES or file.stat().st_size > _MAX_FILE_BYTES:
            continue
        scanned += 1
        try:
            lines = _read_text(file).splitlines()
        except OSError:
            continue
        for lineno, line in enumerate(lines, 1):
            if needle in line.lower():
                hits.append(f"{_relative(file)}:{lineno}: {line.strip()[:200]}")
                if len(hits) >= cap:
                    break
    return "\n".join(hits) if hits else f"未找到 {query!r}（已扫描 {scanned} 个文本文件）"


class Tool:
    """一个可调用工具。

    刻意不用 `@dataclass`：Harbor adapter 用 `importlib.util.module_from_spec` +
    `exec_module` 动态加载被测文件，模块不会注册进 `sys.modules`；Python 3.14 的
    `dataclasses` 在解析 `from __future__ import annotations` 的字符串注解时会查
    `sys.modules[cls.__module__].__dict__`，从而抛
    `AttributeError: 'NoneType' object has no attribute '__dict__'`。
    """

    __slots__: ClassVar[tuple[str, ...]] = ("name", "description", "params", "func")

    name: str
    description: str
    params: dict[str, str]
    func: Callable[..., str]

    def __init__(
        self,
        name: str,
        description: str,
        params: dict[str, str],
        func: Callable[..., str],
    ) -> None:
        self.name = name
        self.description = description
        self.params = params
        self.func = func


TOOLS: tuple[Tool, ...] = (
    Tool(
        "calculator",
        "计算一个数学表达式（不支持变量与函数调用）。",
        {"expression": "表达式，例如 123*456"},
        _calculator,
    ),
    Tool(
        "list_files",
        "列出工作区内的文件与目录，用于先确认有哪些资料可读。",
        {"path": "相对工作区的目录路径，默认 '.'"},
        _list_files,
    ),
    Tool(
        "read_file",
        "读取工作区内一个文本文件的内容（自动识别 UTF-8 / GB18030）。",
        {"path": "相对工作区的文件路径", "max_chars": "最多返回字符数，默认 4000"},
        _read_file,
    ),
    Tool(
        "search_text",
        "在工作区的文本文件中检索关键字，返回带行号的匹配行。",
        {"query": "要检索的关键字", "path": "检索范围（文件或目录），默认 '.'", "max_matches": "最多返回匹配数，默认 8"},
        _search_text,
    ),
)


def _run_tool(name: str, raw_input: str, tools: tuple[Tool, ...] = TOOLS) -> str:
    """解析 Action Input 并执行工具；所有异常都转成 Observation 文本，不中断循环。"""
    tool = next((t for t in tools if t.name == name.lower()), None)
    if tool is None:
        return f"错误：未知工具 {name!r}。可用工具：{', '.join(t.name for t in tools)}"

    text = raw_input.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()

    valid_params = inspect.signature(tool.func).parameters
    args: dict[str, Any] = {}
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                args = {k: v for k, v in parsed.items() if k in valid_params}
        except json.JSONDecodeError:
            pass
    if not args and text:
        first = next(iter(valid_params))
        args = {first: text}

    try:
        result = str(tool.func(**args))
    except Exception as exc:
        result = f"错误：{type(exc).__name__}: {exc}"
    if len(result) > _MAX_OBSERVATION:
        result = result[:_MAX_OBSERVATION] + f"\n...(工具输出已截断，共 {len(result)} 字符)"
    return result or "(工具无输出)"


# --------------------------------------------------------------------------- #
# ReAct 提示词与回复解析
# --------------------------------------------------------------------------- #

_FORMAT_HINT = (
    "继续。请严格按格式输出：需要工具就输出 Action / Action Input，"
    "可以直接回答就输出 Final Answer。"
)


def _build_system_prompt(tools: tuple[Tool, ...]) -> str:
    docs: list[str] = []
    for tool in tools:
        params = "，".join(f"{k}：{v}" for k, v in tool.params.items())
        docs.append(f"- {tool.name}({', '.join(tool.params)})：{tool.description} 参数：{params}")

    return f"""你是一个遵循 ReAct（Reasoning + Acting）范式的助手：先思考，再决定是否调用工具，观察结果后继续推理，直到能给出最终答案。

# 可用工具
{chr(10).join(docs)}

# 输出格式（每轮严格二选一）
需要调用工具时：
Thought: <一句话说明为什么要用工具>
Action: <工具名>
Action Input: <参数 JSON 对象；单参数工具也可以直接写参数值>

可以直接回答时：
Thought: <一句话说明依据>
Final Answer: <最终答案>

# 规则
- 常识/知识类问题直接用 Final Answer 回答，不要为了「走流程」而调用工具。
- 只在需要计算、查看本地文件、或核实原文证据时调用工具；每轮最多调用一个工具，且不重复调用同一工具得到相同结果。
- Action 必须是上表中的工具名；不要编造 Observation，工具结果由系统给出。
- 工具报错时换一种方式，或在没有工具帮助的情况下给出最可靠的答案。
- Final Answer 只写答案本身，不附加过程、解释、格式标签或 Markdown 代码块；之后不要再输出任何内容。
- 不需要写文件：运行环境会自动保存 Final Answer 的内容，你只需返回答案文本。
"""


_ACTION_RE = re.compile(r"(?im)^\s*Action\s*:\s*(.+?)\s*$")
_INPUT_RE = re.compile(
    r"(?ims)^\s*Action\s+Input\s*:\s*(.*?)(?=^\s*(?:Thought|Action|Final\s+Answer|Observation)\s*:|\Z)"
)
_FINAL_RE = re.compile(r"(?ims)^\s*Final\s+Answer\s*:\s*(.*)\Z")


def _clean(text: str) -> str:
    """去掉代码块围栏，并把常见的加粗标签 / 中文冒号归一成标准 ReAct 标签。"""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    # 只归一化「标签后的冒号」，避免改动答案正文里的中文标点。
    text = re.sub(r"(?im)^\s*最终答案\s*[:：]\s*", "Final Answer: ", text)
    text = re.sub(
        r"(?im)^(\s*(?:Thought|Action Input|Action|Final Answer|Observation)\s*)：",
        r"\1:",
        text,
    )
    text = re.sub(
        r"(?im)^\s*\*\*\s*(Thought|Action Input|Action|Final Answer)\s*:\s*\*\*\s*",
        r"\1: ",
        text,
    )
    text = re.sub(
        r"(?im)^\s*\*\*\s*(Thought|Action Input|Action|Final Answer)\s*\*\*\s*:\s*",
        r"\1: ",
        text,
    )
    return text


def _message_text(response: Any) -> str:
    content: Any = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "".join(parts)
    return str(content)


def _parse_reply(text: str) -> tuple[str | None, str, str]:
    """返回 (action, action_input, final_answer)。"""
    final = _FINAL_RE.search(text)
    if final:
        return None, "", final.group(1).strip()
    action = _ACTION_RE.search(text)
    if not action:
        return None, "", ""
    name = action.group(1).strip().strip("`'\"").split("(")[0].strip()
    raw_input = _INPUT_RE.search(text)
    return name, (raw_input.group(1).strip() if raw_input else ""), ""


def _trace(verbose: bool, text: str) -> None:
    if verbose:
        print(text, file=sys.stderr)


# --------------------------------------------------------------------------- #
# Agent
# --------------------------------------------------------------------------- #


class SimpleReActAgent:
    """最小的 ReAct 循环：模型产出 Action，代码执行工具并回填 Observation。"""

    model: Any
    tools: tuple[Tool, ...]
    max_steps: int
    system_prompt: str

    def __init__(self, chat_model: Any, *, tools: tuple[Tool, ...] = TOOLS, max_steps: int = 6):
        self.model = chat_model
        self.tools = tools
        self.max_steps = max_steps
        self.system_prompt = _build_system_prompt(tools)

    def run(self, question: str, *, verbose: bool = False) -> str:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": question},
        ]
        for step in range(1, self.max_steps + 1):
            reply = _clean(_message_text(self.model.invoke(messages)))
            _trace(verbose, f"--- step {step} ---\n{reply}")
            action, action_input, final = _parse_reply(reply)
            if final:
                return final
            if action:
                observation = _run_tool(action, action_input, self.tools)
                _trace(verbose, f"--- observation ---\n{observation}")
                messages.append({"role": "assistant", "content": reply})
                messages.append({"role": "user", "content": f"Observation: {observation}"})
            else:
                # 没按格式输出：把回复原样带回并提醒，避免直接把中间推理当答案。
                messages.append({"role": "assistant", "content": reply})
                messages.append({"role": "user", "content": _FORMAT_HINT})

        # 轮数耗尽：强制收尾，保证一定返回答案文本。
        messages.append(
            {"role": "user", "content": "已达工具调用上限。请立即输出 Final Answer 给出最终答案，不要再调用工具。"}
        )
        reply = _clean(_message_text(self.model.invoke(messages)))
        _, _, final = _parse_reply(reply)
        return final or reply


def _default_max_steps() -> int:
    try:
        return max(1, min(int(os.getenv("DS_REACT_MAX_STEPS", "6")), 50))
    except ValueError:
        return 6


_agent = SimpleReActAgent(model, max_steps=_default_max_steps()) if model is not None else None


def chat(msg: str, *, verbose: bool | None = None) -> str:
    """与 `agent.py::chat` 同签名：返回最终答案文本；异常时返回空串。"""
    if _agent is None:
        return ""
    if verbose is None:
        verbose = os.getenv("DS_REACT_VERBOSE", "").lower() in {"1", "true", "yes"}
    try:
        return _agent.run(msg, verbose=verbose)
    except ValueError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
    except ConnectionError as exc:
        print(f"网络连接错误：{exc}", file=sys.stderr)
    except Exception as exc:
        print(f"异常：{type(exc).__name__}: {exc}", file=sys.stderr)
    return ""


if __name__ == "__main__":
    question = " ".join(sys.argv[1:]) or "《西游记》中，孙悟空被如来佛祖压在五行山下多少年？"
    print(chat(question, verbose=True))
