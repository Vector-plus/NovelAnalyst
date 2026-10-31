"""解说词 7 个只读工具 + read_file/ls 基础能力。

对应设计文档《03-核心图设计_解说词生成.md》§4 的只读工具清单。工具用 closure 绑定
一个 :class:`ReadOnlyFs` 实例（锚定 `novel_root`），保证**只读 + 路径穿越防护**。

工具清单（7 个业务工具 + 2 个文件基础能力）：

- `read_file` / `ls`：读任意索引/原文文件（ReadOnlyFs 封装）。
- `load_manifest`：读 `manifest.json`（index_version / published_through / 各 ref）。
- `load_task_routes`：读 `navigation/task-routes.json` 中指定 task_type 的路由。
- `load_entity`：读实体入口 index.json + 阶段摘要 stages/*.md。
- `load_chapter_ledger`：读 `ledger/chapters/{chapter_id}.json`。
- `search_name`：名字 → 实体 ref（精确 → 模糊 → LLM 语义召回三层）。
- `ask_clarification`：向用户澄清阻塞性问题（返回信号标记）。
- `report_gap`：报告材料缺口（返回信号标记）。

三条确定性护栏：名字消歧（存在性由代码裁决）、覆盖预检（manifest 的 coverage）、
只读契约（无任何写方法）。
"""

from __future__ import annotations

import json

from langchain_core.tools import tool

from deerflow_simple.config import SimpleConfig
from deerflow_simple.narration.names import (
    collect_name_surfaces,
    nfkc,
    resolve_name_exact,
    resolve_name_fuzzy,
)
from deerflow_simple.narration.read_only import ReadOnlyFs

# ---------------------------------------------------------------------------
# search_name 第 3 层 · LLM 语义召回 System Prompt（复用 04-prompt_解说任务核查.md §2）
# 模块级常量：禁止 f-string 插值，保证前缀缓存稳定；动态变量只进 User 段。
# ---------------------------------------------------------------------------
RESOLVE_NAME_SYSTEM = (
    "你是「名称语义召回员」。你的唯一任务：在给定的候选名字列表中，"
    "找出与用户输入最可能指代同一个人的那个名字。\n\n"
    "## 铁律（违反即失败）\n"
    "1. 候选列表是唯一事实来源。你只能从列表里挑一个名字返回，严禁输出列表之外的名字。\n"
    "2. 不做存在性裁决。列表里没有相似名字时，必须返回 matched=false，即使你确信现实/小说里有这么个人。\n"
    "3. 置信度诚实。confidence 表示「输入名与候选名指代同一人的把握」，不足 0.8 必须 matched=false。\n"
    "4. 只输出一个最优匹配。\n\n"
    "## 判断要点\n"
    "- 常见别名/简称/绰号/错别字（如「猴子」「猴哥」「孙行者」可能都指「孙悟空」）。\n"
    "- 只凭读音相近或单字相同不足以匹配，需整体语义确实指同一人。\n"
    "- 拿不准时宁可 matched=false，也不要误匹配。\n\n"
    "## 输出\n"
    '只输出 JSON：{"matched": true|false, "matched_name": "候选名", "confidence": 0.0-1.0, "reason": "..."}。'
)


def _read_json(fs: ReadOnlyFs, path: str) -> dict | list | None:
    text = fs.read_file(path)
    if text.startswith("("):
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _semantic_recall_name(name: str, all_surfaces: list[str], config: SimpleConfig) -> dict | None:
    """search_name 第 3 层：LLM 语义召回（仅前两层全 miss 才触发）。

    代码负责「真实性」（拉出全部真实名字），LLM 只负责「挑选」。两道闸：
    1. 返回的 matched_name 必须在候选列表内，否则 no_match。
    2. confidence < 0.8 视为 no_match。
    """
    if not all_surfaces:
        return None
    from deerflow_simple.model import create_chat_model

    candidates = "\n".join(f"- {s}" for s in all_surfaces)
    user_prompt = (
        f"【待匹配输入名】{name}\n\n"
        f"【候选名字列表（真实存在于索引中，只能从这里选）】\n{candidates}\n\n"
        "请判断输入名与列表中哪个名字最可能指同一人，并按 schema 输出。"
    )
    try:
        model = create_chat_model(config, temperature=0.0)
        resp = model.invoke(RESOLVE_NAME_SYSTEM + "\n\n" + user_prompt)
        text = resp.content if isinstance(resp.content, str) else str(resp.content)
    except Exception:
        return None

    # 提取 JSON（容错剥离可能的外围文本）
    m = __import__("re").search(r"\{[\s\S]*\}", text.strip())
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not data.get("matched"):
        return None
    matched_name = str(data.get("matched_name", "")).strip()
    confidence = data.get("confidence", 0.0)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.0
    # 两道闸：列表外名字 / 低置信度 → no_match
    if matched_name not in all_surfaces or confidence < 0.8:
        return None
    return {"matched_name": matched_name, "confidence": confidence}


def build_narration_tools(novel_root: str, config: SimpleConfig) -> list:
    """构建解说词的只读工具集，锚定 novel_root。"""
    fs = ReadOnlyFs(novel_root)

    @tool
    def read_file(path: str) -> str:
        """读取索引树中的一个文本文件（相对 novel_root 的路径或绝对路径）。"""
        return fs.read_file(path)

    @tool
    def ls(path: str = ".") -> str:
        """列出索引树目录内容。"""
        return fs.list_dir(path)

    @tool
    def load_manifest() -> str:
        """读取 novel/manifest.json，返回索引版本、已发布覆盖、各导航 ref。"""
        data = _read_json(fs, "manifest.json")
        if data is None:
            return "(manifest.json 不可读或不存在)"
        return json.dumps(data, ensure_ascii=False, indent=2)

    @tool
    def load_task_routes(task_type: str) -> str:
        """读取 navigation/task-routes.json 中指定 task_type 的路由（入口/必读/可选/停止条件）。"""
        data = _read_json(fs, "navigation/task-routes.json")
        if not isinstance(data, dict):
            return "(task-routes.json 不可读或不存在)"
        defaults = data.get("defaults", {})
        route = None
        for r in data.get("routes", []) or []:
            if isinstance(r, dict) and r.get("task_type") == task_type:
                route = r
                break
        if route is None:
            return f"(未找到 task_type={task_type} 的路由)"
        return json.dumps({"defaults": defaults, "route": route}, ensure_ascii=False, indent=2)

    @tool
    def load_entity(ref: str) -> str:
        """读取实体入口 index.json + 阶段摘要 stages/*.md。

        ref 可以是实体入口路径（如 characters/char-0001/index.json）或实体 record_id
        （如 char-0001，通过名字索引定位路径）。
        """
        # 若 ref 是 record_id（不含 / 且不以 .json 结尾），尝试从名字索引定位
        if "/" not in ref and not ref.endswith(".json"):
            located = None
            for s in collect_name_surfaces(fs):
                if (s.get("entity_ref") or {}).get("record_id") == ref:
                    located = (s.get("entity_ref") or {}).get("path")
                    break
            if located:
                ref = located
        index_path = ref if ref.endswith(".json") else f"{ref}/index.json"
        data = _read_json(fs, index_path)
        parts = []
        if data is not None:
            parts.append(f"== {index_path} ==\n" + json.dumps(data, ensure_ascii=False, indent=2))
        else:
            parts.append(f"== {index_path} ==\n(不可读或不存在)")
        # 阶段摘要：同目录 stages/*.md
        # 注意 list_dir 返回的是相对 novel_root 的完整路径，直接用于 read_file，不再拼前缀。
        entity_dir = index_path.rsplit("/", 1)[0]
        stages = fs.list_dir(f"{entity_dir}/stages")
        if not stages.startswith("("):
            for line in stages.splitlines():
                if line.endswith(".md"):
                    content = fs.read_file(line)
                    parts.append(f"\n== {line} ==\n{content}")
        return "\n".join(parts)

    @tool
    def load_chapter_ledger(chapter_id: str) -> str:
        """读取 ledger/chapters/{chapter_id}.json（章节摘要/事件/claims）。"""
        data = _read_json(fs, f"ledger/chapters/{chapter_id}.json")
        if data is None:
            return f"(ledger/chapters/{chapter_id}.json 不可读或不存在)"
        return json.dumps(data, ensure_ascii=False, indent=2)

    @tool
    def search_name(name: str) -> str:
        """名字 → 实体 ref。三层匹配：NFKC 精确 → difflib 模糊 → LLM 语义召回。

        返回 JSON：status=unique/ambiguous/fuzzy/not_found + matches 候选列表。
        """
        # 第 1 层：精确匹配
        exact = resolve_name_exact(fs, name)
        if len(exact) == 1:
            return json.dumps(
                {"status": "unique", "name": name, "matches": exact},
                ensure_ascii=False,
            )
        if len(exact) > 1:
            return json.dumps(
                {"status": "ambiguous", "name": name, "matches": exact},
                ensure_ascii=False,
            )

        # 第 2 层：模糊匹配
        fuzzy = resolve_name_fuzzy(fs, name)
        if fuzzy:
            return json.dumps(
                {"status": "fuzzy", "name": name, "matches": fuzzy},
                ensure_ascii=False,
            )

        # 第 3 层：LLM 语义召回（仅前两层全 miss 才触发）
        all_surfaces = list(
            {nfkc(s["surface"]) for s in collect_name_surfaces(fs) if nfkc(s["surface"])}
        )
        recalled = _semantic_recall_name(name, all_surfaces, config)
        if recalled is not None:
            # 语义命中后回到精确层拿完整实体信息
            hit = resolve_name_exact(fs, recalled["matched_name"])
            if hit:
                return json.dumps(
                    {"status": "unique", "name": name, "matches": hit, "semantic": True},
                    ensure_ascii=False,
                )
        return json.dumps({"status": "not_found", "name": name, "matches": []}, ensure_ascii=False)

    @tool
    def ask_clarification(question: str) -> str:
        """向用户澄清阻塞性问题（主体歧义/缺必填字段等）。返回澄清信号，由上层转交用户。"""
        return f"[CLARIFICATION_NEEDED] {question}"

    @tool
    def report_gap(gap: str) -> str:
        """报告材料缺口（索引覆盖不全、证据不足等）。返回缺口信号，最终并入结果元信息。"""
        return f"[GAP_REPORTED] {gap}"

    return [
        read_file,
        ls,
        load_manifest,
        load_task_routes,
        load_entity,
        load_chapter_ledger,
        search_name,
        ask_clarification,
        report_gap,
    ]


def build_skill_reference_tool(skill_dir: str):
    """构建「读 skill 资源」只读工具集，锚定 skill 目录。

    SKILL.md 正文里引用了大量 references 文件（retrieval-playbook.md、style-guide-*.md、
    structure-templates.md、evidence-and-boundary.md、examples/*.md）。这些是「方法论资源」，
    与小说索引数据（novel_root）无关，**无法通过锚定 novel_root 的 read_file 读取**。

    本工具复用 :class:`ReadOnlyFs`（root 指向 skill 目录），让 NarrationAgent 在运行时
    **按需加载**对应主题的风格/检索指南——这正是「不同类型解说任务风格与检索方式不同」
    的落地方式：不用一次性把全部 references 注入 prompt，Agent 读到哪个 task_type，
    就加载哪个 style-guide-*.md。

    返回两个工具：
    - `read_skill_reference(path)`：读取 skill 资源文件（references/、examples/ 下任意文件）。
    - `list_skill_references(path)`：递归列出 skill 资源目录下的所有文件，让 LLM 先摸清
      references/ 里到底有哪些风格指南/检索指南可用，再决定读哪个。
    """
    fs = ReadOnlyFs(skill_dir)

    @tool
    def read_skill_reference(path: str) -> str:
        """读取 skill 资源文件（相对 skill 根目录，如 references/style-guide-chapter.md）。"""
        return fs.read_file(path)

    @tool
    def list_skill_references(path: str = "references") -> str:
        """递归列出 skill 资源目录下的所有文件（默认 references/，可传 examples 等子目录）。

        让 LLM 先识别 references/ 下有哪些可用文件（风格指南、检索指南、结构模板、证据边界），
        再按需用 read_skill_reference 读取。仅返回文件路径，不返回目录本身。
        """
        result: list[str] = []

        def walk(rel: str):
            listing = fs.list_dir(rel)
            if listing.startswith("("):
                # 不是目录（可能是文件），直接记下
                if fs.exists(rel) and not fs.is_dir(rel):
                    result.append(rel)
                return
            for entry in listing.splitlines():
                entry = entry.strip()
                if not entry:
                    continue
                if fs.is_dir(entry):
                    walk(entry)
                else:
                    result.append(entry)

        walk(path)
        if not result:
            return f"(目录为空或不存在: {path})"
        return "\n".join(sorted(result))

    return [read_skill_reference, list_skill_references]
