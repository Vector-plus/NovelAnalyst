"""prescan 节点 —— 单卷并发扫读（fan-out）+ 单次阶段合并（fan-in）。

对应设计文档《03-核心图设计_索引生成.md》§2.2 N3 + 《04-prompt_第一阶段粗读.md》§1。

编排：
1. 读 ``source/index.json`` 获得卷清单（vol_id + 章节范围）。
2. ``asyncio.gather`` 并发调用 ScanVolReActAgent 扫每卷，收集 VolReport。
3. **滚动增量**调用 StagePlanMergeAgent 合并为 stage-plan draft（每卷一次，输入
   「已合并骨架 + 单卷 VolReport」，避免长篇小说全量 merge 超出上下文窗口）。
4. 节点函数（确定性）计算 scanned_ranges、校验连续性并落盘
   ``navigation/stage-plan.json``（Agent 不写文件）。
5. phase → ``review_plan``。

一期边界：不做 ``_staging/prescan/vol-xxx.done`` 幂等标记（最短链路优先），
checkpoint 恢复时会从 prescan 节点重入并重扫；幂等优化二期补。
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from deerflow_simple.config import SimpleConfig
from deerflow_simple.index_builder.agents.runner import run_agent_streaming
from deerflow_simple.index_builder.agents.scan_vol import (
    build_scan_vol_agent,
    build_scan_vol_prompt,
)
from deerflow_simple.index_builder.agents.stage_plan_merge import (
    build_stage_plan_merge_agent,
    build_stage_plan_merge_prompt,
)
from deerflow_simple.index_builder.state import BuildState

# Agent 缓存：按 novel_root 复用编译好的 graph（无状态，可安全复用）。
_scan_agent_cache: dict[str, object] = {}
_merge_agent_cache: dict[str, object] = {}


def _get_scan_agent(config: SimpleConfig, novel_root: str):
    if novel_root not in _scan_agent_cache:
        _scan_agent_cache[novel_root] = build_scan_vol_agent(config, novel_root)
    return _scan_agent_cache[novel_root]


def _get_merge_agent(config: SimpleConfig, novel_root: str):
    if novel_root not in _merge_agent_cache:
        _merge_agent_cache[novel_root] = build_stage_plan_merge_agent(config, novel_root)
    return _merge_agent_cache[novel_root]


def _parse_json(text: str) -> dict:
    """从 Agent 输出里提取 JSON 对象（容错剥离可能的外围文本 / markdown 代码块）。"""
    text = (text or "").strip()
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        text = m.group(0)
    return json.loads(text)


def _is_rate_limited(exc: Exception) -> bool:
    """判断异常是否为服务端限流（429 / rate limit / 限流）。

    公共模型服务（如 venus 100/min）返回 429 时，错误信息形如
    ``Error code: 429 - {'error': {'message': '...限流...'}}``。识别后需用更长退避
    （限流窗口 60s，短退避无效），而非普通的 2s/4s 退避。
    """
    msg = str(exc).lower()
    return "429" in msg or "限流" in msg or "rate limit" in msg or "rate_limit" in msg


def _list_volumes(novel_root: str) -> list[dict]:
    """读 source/index.json，返回卷清单 [{vol_id, start, end}]。"""
    source_index = json.loads(
        (Path(novel_root) / "source" / "index.json").read_text(encoding="utf-8")
    )
    vols = []
    for entry in source_index.get("entries", []):
        path = entry.get("target", {}).get("path", "")
        vol_id = path.split("/")[1] if "/" in path else path
        ranges = entry.get("chapter_ranges") or [{}]
        start = ranges[0].get("start", 1)
        end = ranges[0].get("end", start)
        vols.append({"vol_id": vol_id, "start": start, "end": end})
    return vols


def _merge_scanned_chapters(scanned_by_vol: list[list[int]]) -> list[dict]:
    """把各卷 scanned_chapters 的并集（去重、升序）压成连续区间列表。

    LLM 产出阶段边界时**不依赖** scanned_chapters（该字段已从 merge 输入剔除），
    `stage-plan.scanned_ranges` 由本函数确定性计算，杜绝 LLM 幻觉/遗漏。
    """
    all_chapters = sorted({c for chs in scanned_by_vol for c in chs})
    ranges: list[dict] = []
    for ch in all_chapters:
        if ranges and ch == ranges[-1]["end"] + 1:
            ranges[-1]["end"] = ch
        else:
            ranges.append({"start": ch, "end": ch})
    return ranges


def _validate_stage_plan_stages(stages: list, total_chapters: int) -> list[str]:
    """确定性校验 stages 的 chapter_ranges 连续、无重叠、无遗漏、首尾对齐。

    返回问题列表（空表示通过）。这是对 LLM 输出的**兜底校验**：不 fail 任务，
    只把问题回写到 merge_notes 供 N4 人工审核时看到（一期宽松策略）。
    """
    flat: list[tuple[int, int]] = []
    for st in stages:
        for r in st.get("chapter_ranges", []):
            flat.append((r.get("start", 1), r.get("end", r.get("start", 1))))
    flat.sort()

    issues: list[str] = []
    if not flat:
        return ["无任何 stage"]
    if flat[0][0] != 1:
        issues.append(f"第一个 stage 起始 {flat[0][0]} != 1")
    if flat[-1][1] != total_chapters:
        issues.append(f"最后一个 stage 结束 {flat[-1][1]} != total_chapters({total_chapters})")
    prev_end = 0
    for start, end in flat:
        if start != prev_end + 1:
            issues.append(f"chapter_ranges 不连续/重叠：期望从 {prev_end + 1} 开始，实际 {start}")
        if end < start:
            issues.append(f"非法区间 {start}~{end}")
        prev_end = max(prev_end, end)
    return issues


def make_prescan_node(config: SimpleConfig):
    """构造 prescan 节点函数（闭包捕获 config）。"""

    async def prescan_node(state: BuildState) -> BuildState:
        novel_root = state["novel_root"]
        novel_id = state["novel_id"]
        source_version = state["source_version"]
        total_chapters = state["total_chapters"]

        # ① 卷清单
        vols = _list_volumes(novel_root)
        if not vols:
            raise ValueError("source/index.json 无卷清单，请先完成 skeleton 切块")

        scan_agent = _get_scan_agent(config, novel_root)

        # ② 受控并发扫描（Python 控制并发，不是 LLM 决策）。
        # 用 Semaphore 限制同时在跑的卷数，避免全量 asyncio.gather 并发扫几十卷时，
        # N 个 ScanVolReActAgent（每个含多轮 LLM turn）瞬间打爆公共模型服务限流（429）。
        sem = asyncio.Semaphore(config.index_scan_concurrency)

        async def scan_one(index: int, vol: dict) -> dict:
            async with sem:
                prompt = build_scan_vol_prompt(
                    novel_root,
                    vol["vol_id"],
                    vol["start"],
                    vol["end"],
                    index + 1,
                    len(vols),
                )
                last_error: Exception | None = None
                for attempt in range(3):
                    try:
                        text = await run_agent_streaming(scan_agent, prompt, config)
                        return _parse_json(text)
                    except Exception as exc:  # noqa: BLE001
                        last_error = exc
                        if attempt < 2:
                            if _is_rate_limited(exc):
                                # 429 限流：限流窗口 60s，需长退避；15s/30s 给窗口清空时间
                                await asyncio.sleep(15 * (attempt + 1))
                            else:
                                await asyncio.sleep(2 * (attempt + 1))
                        continue
                raise RuntimeError(
                    f"卷 {vol['vol_id']} 扫读失败（重试 3 次仍失败）: {last_error}"
                )

        vol_reports = await asyncio.gather(
            *[scan_one(i, v) for i, v in enumerate(vols)]
        )

        # ③ 滚动增量合并（StagePlanMergeAgent 只输出 JSON，不写文件）
        # 逐卷滚动：每次只喂「已合并骨架 + 单卷 VolReport」，避免长篇小说全量 VolReports
        # 超出模型上下文窗口（此前 14 卷 2076 章全量 merge 导致模型静默返回空）。
        merge_agent = _get_merge_agent(config, novel_root)
        title = "novel"
        # 从 manifest 读 title（skeleton 已写入）
        manifest_path = Path(novel_root) / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            title = manifest.get("title", title)

        # 初始空骨架（三块结构，与 System Prompt 输出格式一致）
        cur_skeleton: dict = {"stages": [], "character_candidates": [], "merge_notes": []}
        scanned_by_vol: list[list[int]] = []

        for i, vol_report in enumerate(vol_reports):
            vol_id = vol_report.get("vol_id", f"vol-{i + 1:03d}")
            is_last = (i == len(vol_reports) - 1)

            # 剔除 scanned_chapters：merge 不需要它（scanned_ranges 由节点确定性计算），
            # 且它是长篇小说输入膨胀的最大来源（连续章节被 LLM 展开成完整列表）。
            scanned_by_vol.append(vol_report.get("scanned_chapters", []))
            vol_report_for_merge = {
                k: v for k, v in vol_report.items() if k != "scanned_chapters"
            }

            merge_prompt = build_stage_plan_merge_prompt(
                novel_root,
                novel_id,
                title,
                None,
                source_version,
                total_chapters,
                len(vols),
                vol_id,
                i + 1,
                json.dumps(cur_skeleton, ensure_ascii=False),
                json.dumps(vol_report_for_merge, ensure_ascii=False),
                is_last,
            )

            # 单卷合并重试 ≤3 + 退避（区分 429 长退避 / 普通短退避）
            merged: dict | None = None
            merge_error: Exception | None = None
            for attempt in range(3):
                try:
                    merge_text = await run_agent_streaming(merge_agent, merge_prompt, config)
                    merged = _parse_json(merge_text)
                    break
                except Exception as exc:  # noqa: BLE001
                    merge_error = exc
                    if attempt < 2:
                        if _is_rate_limited(exc):
                            # 429 限流：长退避（限流窗口 60s）
                            await asyncio.sleep(15 * (attempt + 1))
                        else:
                            await asyncio.sleep(2 * (attempt + 1))
                    continue
            if merged is None:
                raise RuntimeError(
                    f"卷 {vol_id} 合并失败（重试 3 次仍失败）: {merge_error}"
                )

            # 更新累积骨架（滚动传递到下一卷；缺字段时回退旧值，防 LLM 漏字段）
            cur_skeleton = {
                "stages": merged.get("stages", cur_skeleton["stages"]),
                "character_candidates": merged.get(
                    "character_candidates", cur_skeleton["character_candidates"]
                ),
                "merge_notes": merged.get("merge_notes", cur_skeleton["merge_notes"]),
            }

        stage_plan = cur_skeleton

        # ④ 确定性落盘（防 LLM 幻觉：强制修正关键字段）
        stage_plan["novel_id"] = novel_id
        stage_plan["source_version"] = source_version
        stage_plan["status"] = "draft"
        stage_plan["revision"] = 1
        stage_plan.setdefault("schema_version", "2.0")
        stage_plan.setdefault("id", "stage-plan")
        stage_plan.setdefault("kind", "stage_plan")
        stage_plan.setdefault("safe_through", 1)
        # scanned_ranges 由节点确定性计算（LLM 不产出该字段）
        stage_plan["scanned_ranges"] = _merge_scanned_chapters(scanned_by_vol)
        # 连续性兜底校验（不 fail 任务，问题回写 merge_notes 供 N4 人工审核时看到）
        continuity_issues = _validate_stage_plan_stages(
            stage_plan.get("stages", []), total_chapters
        )
        if continuity_issues:
            stage_plan.setdefault("merge_notes", []).append(
                "[节点校验] 阶段连续性存疑: " + "; ".join(continuity_issues)
            )

        stage_plan_path = Path(novel_root) / "navigation" / "stage-plan.json"
        stage_plan_path.parent.mkdir(parents=True, exist_ok=True)
        stage_plan_path.write_text(
            json.dumps(stage_plan, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        # 只返回需要更新的字段（不展开整个 state，避免 errors 聚合字段重复累加）
        return {"phase": "review_plan"}

    return prescan_node
