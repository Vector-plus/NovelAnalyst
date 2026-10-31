"""generate_narration —— 解说词生成工具入口（供 lead_agent 调用）。

对应设计文档《03-核心图设计_解说词生成.md》§9。这是「tool-as-workflow-entry」：
lead_agent 通过本工具触发解说，工具内部 invoke 一个 NarrationAgent 并同步返回。

关键设计：
- **参数合法性短路**：task_type 枚举 / 必填矩阵 / 禁用参数在入口用纯 if/else 校验，
  不花 token、不交给 LLM。
- **task_type 五类以 SKILL.md 为准**（skill 可调整，本文件跟随调整）。
- **同步返回**：解说词是秒~分钟级短任务，直接返回完整稿件，无异步轮询。
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Annotated

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from deerflow_simple.config import SimpleConfig
from deerflow_simple.narration.agent import build_narration_agent
from deerflow_simple.spaces.paths import resolve_novel_index_path, resolve_novel_result_path
from deerflow_simple.stream import (
    EVENT_MESSAGE,
    SOURCE_NARRATION,
    BudgetGuard,
    emit_event,
    estimate_tokens,
    parse_stream_chunk,
)

# 五类 task_type（与 SKILL.md 输入契约一致）
_TASK_TYPES = (
    "chapter_explanation",
    "biography",
    "faction_landscape",
    "worldbuilding",
    "emotional_arc",
)

# 必填矩阵（SKILL.md 输入契约表格）
_SUBJECT_REQUIRED = {"biography", "worldbuilding", "emotional_arc"}
_FOCUS_REQUIRED = {"chapter_explanation"}

# NarrationAgent 缓存：按 novel_root 复用编译好的 graph（无状态，可安全复用）
_agent_cache: dict[str, object] = {}


def _validate(task_type: str, subject: str | None, focus_ranges: list | None) -> tuple[bool, str | None]:
    """纯 if/else 参数校验，不花 token。返回 (是否通过, 错误信息)。"""
    if task_type not in _TASK_TYPES:
        return False, f"未知 task_type: {task_type}（应为 {'/'.join(_TASK_TYPES)} 之一）"
    if task_type in _SUBJECT_REQUIRED and not subject:
        return False, f"task_type={task_type} 需要 subject（人物名/设定名/人物对）"
    if task_type in _FOCUS_REQUIRED and not focus_ranges:
        return False, f"task_type={task_type} 需要 focus_ranges（章节范围）"
    return True, None


def resolve_novel_root(config: SimpleConfig, novel_id: str) -> Path:
    """根据 novel_id 确定性映射出小说**索引树根目录**（不交给 LLM）。

    注意两层目录，本函数返回的是**索引树根**（index root），不是小说空间根
    （space root）：
    - space root = ``config.workspace_path / novel_id``（存原文 source/novel.txt）
    - index root = ``config.workspace_path / novel_id / novel``（存 manifest.json
      与各主题索引，与 novel-index-creator 约定一致）

    lead_agent 调用 ``generate_narration`` 时只传 ``novel_id``，本函数在**前置代码**
    里完成 id → 索引树根路径的映射，避免让 LLM 猜测或幻觉绝对路径。

    护栏（纯代码、零 token）：
    - **防路径穿越**：``novel_id`` 解析后必须仍位于 workspace 内（拒绝 ``../`` 等）。
    - **存在性校验**：索引目录不存在直接抛错，不让 NarrationAgent 在空目录里瞎跑。
    """
    root = resolve_novel_index_path(config, novel_id)
    if not root.is_dir():
        raise FileNotFoundError(f"小说索引目录不存在: {root}（请先建立索引）")
    return root


def _get_agent(novel_root: str, config: SimpleConfig, skills_dir: str | None):
    """按 novel_root 缓存 NarrationAgent。"""
    if novel_root not in _agent_cache:
        _agent_cache[novel_root] = build_narration_agent(config, novel_root, skills_dir)
    return _agent_cache[novel_root]


def _build_prompt(
    task_type: str,
    subject: str | None,
    focus_ranges: list | None,
    extra_hint: str | None,
    output_language: str,
) -> str:
    """把结构化输入拼成 NarrationAgent 的任务描述。"""
    parts = [f"请生成解说词。task_type={task_type}"]
    if subject:
        parts.append(f"subject={subject}")
    if focus_ranges:
        parts.append(f"focus_ranges={focus_ranges}")
    if extra_hint:
        parts.append(f"extra_hint={extra_hint}")
    parts.append(f"output_language={output_language}")
    parts.append("请严格按你的 SKILL.md 主流程执行。")
    return "\n".join(parts)


def _sanitize_filename(part: str) -> str:
    """把 subject / focus_ranges 转成安全文件名片段。

    去除路径分隔符与空白，保留中文；截断到 50 字符避免文件名过长。
    """
    cleaned = re.sub(r'[\\/:*?"<>|\s]+', "_", part).strip("_")
    return cleaned[:50] or "all"


def _build_result_filename(
    task_type: str,
    subject: str | None,
    focus_ranges: list | None,
) -> str:
    """构造解说词结果文件名：``{task_type}_{yyyyMMdd_HHMMSS}_{slug}.md``。

    时间戳到秒级 + slug（subject 优先，否则 focus_ranges，否则 all），
    同名概率极低；若同名会覆盖（同任务同秒同主体，内容基本一致，可接受）。
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if subject:
        slug = _sanitize_filename(subject)
    elif focus_ranges:
        slug = _sanitize_filename("_".join(str(f) for f in focus_ranges))
    else:
        slug = "all"
    return f"{task_type}_{timestamp}_{slug}.md"


def _save_result(result_dir: Path, filename: str, draft: str) -> Path:
    """把解说词正文写入 result 目录，返回落盘后的文件绝对路径。

    纯代码落盘（不经过 LLM）：``mkdir(parents=True, exist_ok=True)`` + UTF-8 写入。
    失败会抛异常，由调用方决定是否阻断主流程。
    """
    result_dir.mkdir(parents=True, exist_ok=True)
    path = result_dir / filename
    path.write_text(draft, encoding="utf-8")
    return path


def build_generate_narration_tool(config: SimpleConfig, skills_dir: str | None = None):
    """构建 generate_narration 工具（挂进 lead_agent 的 extra_tools）。"""

    @tool
    async def generate_narration(
        task_type: str,
        subject: str | None = None,
        focus_ranges: list | None = None,
        extra_hint: str | None = None,
        output_language: str = "zh-CN",
        novel_id: Annotated[str | None, InjectedState("novel_id")] = None,
    ) -> dict:
        """生成小说解说词的唯一入口。处理各种解说任务，当前包括章节剧情、人物传记、势力格局、体系设定和感情线这几类任务的分析解说。

        收到解说类需求时请直接调用本工具，不要用沙箱工具（bash/ls/read_file）自行扫描或读取小说。

        Args:
            task_type: 五选一 chapter_explanation/biography/faction_landscape/worldbuilding/emotional_arc。
            subject: 目标主体（人物名/设定名/人物对），部分 task_type 必填。
            focus_ranges: 章节范围，chapter_explanation 必填。
            extra_hint: 补充侧重点。
            output_language: 输出语言，默认 zh-CN。

        ``novel_id`` 不在 LLM 可见参数中：由代码从 graph state 通过 ``InjectedState``
        注入，LLM 无需也无法决策它。缺失时返回 error，提示先绑定小说空间。

        Returns:
            dict: {status: ok|ambiguity|error, draft, gaps}
        """
        # 0. novel_id 由代码注入（InjectedState），缺失说明对话未绑定小说空间
        if not novel_id:
            return {"status": "error", "error": "当前对话未绑定小说空间（novel_id 缺失），请先传入 novel_id"}

        # 1. 参数合法性短路（纯 if/else，不花 token）
        ok, err = _validate(task_type, subject, focus_ranges)
        if not ok:
            return {"status": "error", "error": err}

        # 2. novel_id → 沙箱路径（前置代码确定性映射，不交给 LLM）
        try:
            novel_root = resolve_novel_root(config, novel_id)
        except (ValueError, FileNotFoundError) as e:
            return {"status": "error", "error": str(e)}

        # 3. 构建/复用 NarrationAgent
        try:
            agent = _get_agent(str(novel_root), config, skills_dir)
        except Exception as e:  # noqa: BLE001
            return {"status": "error", "error": f"装配 NarrationAgent 失败: {e}"}

        # 4. 流式消费（messages 模式），逐事件透传，最终答案累计 + 预算守护
        prompt = _build_prompt(task_type, subject, focus_ranges, extra_hint, output_language)
        draft = ""
        pending_tool_calls: dict[int, dict] = {}
        # 初始预算：用户任务 prompt（system_prompt 是固定开销，不计入循环增量预算）
        guard = BudgetGuard(
            max_tool_calls=config.narration_max_tool_calls,
            token_budget=config.narration_token_budget,
            initial_tokens=estimate_tokens(prompt),
        )
        budget_exceeded = False
        stream = agent.astream(
            {"messages": [HumanMessage(content=prompt)]},
            config={"recursion_limit": config.recursion_limit},
            stream_mode="messages",
        )
        try:
            async for chunk in stream:
                message_part, _metadata = chunk
                events, is_tool_activity = parse_stream_chunk(
                    message_part, pending_tool_calls, SOURCE_NARRATION
                )
                if is_tool_activity:
                    # 工具活动后，最终稿件重新累计（工具调用前的文本是中间话）
                    draft = ""
                for ev in events:
                    guard.feed(ev)
                    if ev["type"] == EVENT_MESSAGE:
                        draft += ev["content"]
                    emit_event(ev)
                # 预算守护（硬约束）：工具调用次数或 token 任一超限即停止扩展，
                # 不再依赖 SKILL.md 的 stop_when 软约束。
                if guard.check():
                    budget_exceeded = True
                    break
        except Exception as e:  # noqa: BLE001
            return {"status": "error", "error": f"解说生成失败: {e}"}
        finally:
            close = getattr(stream, "aclose", None)
            if close is not None:
                try:
                    await close()
                except Exception:
                    pass

        # 信号检测：澄清 / 缺口
        if "[CLARIFICATION_NEEDED]" in draft:
            return {
                "status": "ambiguity",
                "draft": draft,
                "gaps": [],
                "budget_truncated": budget_exceeded,
            }

        gaps = []
        for line in draft.splitlines():
            if "[GAP_REPORTED]" in line:
                gaps.append(line.split("[GAP_REPORTED]", 1)[1].strip())

        # 预算耗尽且还没写出正文：明确报错，而不是返回空稿
        if budget_exceeded and not draft:
            return {
                "status": "error",
                "error": (
                    f"解说生成超出预算（工具调用 {guard.tool_calls} 次 / 估算 token {guard.tokens}），"
                    "请在预算内缩小 focus_ranges 或拆分任务"
                ),
                "budget_truncated": True,
            }

        # 结果落盘：status=ok（含 budget_truncated 的部分成功）时，把稿件写入
        # space_root/result/ 下。落盘失败不阻断主流程，仅在返回里标注 save_error。
        saved_path = None
        save_error = None
        if config.narration_save_result and draft:
            try:
                result_dir = resolve_novel_result_path(config, novel_id)
                filename = _build_result_filename(task_type, subject, focus_ranges)
                saved_path = str(_save_result(result_dir, filename, draft))
            except Exception as e:  # noqa: BLE001 - 落盘失败不阻断解说结果返回
                save_error = str(e)

        result: dict = {
            "status": "ok",
            "draft": draft,
            "gaps": gaps,
            "budget_truncated": budget_exceeded,
            "saved_path": saved_path,
        }
        if save_error is not None:
            result["save_error"] = save_error
        return result

    return generate_narration
