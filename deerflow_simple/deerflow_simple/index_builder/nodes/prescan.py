"""prescan 节点 —— 单卷并发扫读（fan-out）+ 单次阶段合并（fan-in）。

对应设计文档《03-核心图设计_索引生成.md》§2.2 N3 + 《04-prompt_第一阶段粗读.md》§1。

编排：
1. 读 ``source/index.json`` 获得卷清单（vol_id + 章节范围）。
2. ``asyncio.gather`` 并发调用 ScanVolReActAgent 扫每卷，收集 VolReport。
3. 单次调用 StagePlanMergeAgent 合并为 stage-plan draft。
4. 节点函数（确定性）校验并落盘 ``navigation/stage-plan.json``（Agent 不写文件）。
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

        # ③ 单次合并（StagePlanMergeAgent 只输出 JSON，不写文件）
        merge_agent = _get_merge_agent(config, novel_root)
        title = "novel"
        # 从 manifest 读 title（skeleton 已写入）
        manifest_path = Path(novel_root) / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            title = manifest.get("title", title)

        merge_prompt = build_stage_plan_merge_prompt(
            novel_root,
            novel_id,
            title,
            None,
            source_version,
            total_chapters,
            len(vols),
            json.dumps(vol_reports, ensure_ascii=False, indent=2),
        )
        # 合并重试 ≤3 + 指数退避：LLM 偶发返回空/格式错误（reasoning 流截断）时重合并，
        # 退避给服务恢复时间。run_agent_streaming 内部已有 ainvoke 降级，这里再兜一层。
        stage_plan: dict | None = None
        merge_error: Exception | None = None
        for attempt in range(3):
            try:
                merge_text = await run_agent_streaming(merge_agent, merge_prompt, config)
                stage_plan = _parse_json(merge_text)
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
        if stage_plan is None:
            raise RuntimeError(f"阶段计划合并失败（重试 3 次仍失败）: {merge_error}")

        # ④ 确定性落盘（防 LLM 幻觉：强制修正关键字段）
        stage_plan["novel_id"] = novel_id
        stage_plan["source_version"] = source_version
        stage_plan["status"] = "draft"
        stage_plan["revision"] = 1
        stage_plan.setdefault("schema_version", "2.0")
        stage_plan.setdefault("id", "stage-plan")
        stage_plan.setdefault("kind", "stage_plan")
        stage_plan.setdefault("safe_through", 1)

        stage_plan_path = Path(novel_root) / "navigation" / "stage-plan.json"
        stage_plan_path.parent.mkdir(parents=True, exist_ok=True)
        stage_plan_path.write_text(
            json.dumps(stage_plan, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        # 只返回需要更新的字段（不展开整个 state，避免 errors 聚合字段重复累加）
        return {"phase": "review_plan"}

    return prescan_node
