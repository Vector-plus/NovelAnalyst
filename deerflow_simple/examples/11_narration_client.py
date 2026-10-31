"""11 解说词 · SimpleClient 端到端 —— 通过 lead_agent 下发小说解说任务。

与 `10_narration.py` 的区别：
- 10 直接 invoke NarrationAgent（测检索层）；
- 11 走完整链路：SimpleClient(lead_agent) 识别意图 → 调用 generate_narration 工具
  → 工具内部映射 novel_id → NarrationAgent 检索生成。

关键设计（见 narration/AGENT.md）：
- generate_narration 工具的 novel_id 由代码从 graph state 通过 ``InjectedState`` 注入，
  **不出现在 LLM 可见的 tool schema 中**，LLM 无需也无法决策 novel_id。
- 用户在创建对话时通过 ``client.chat(..., novel_id=xxx)`` 传入，prompt 里**不再**提供
  novel_id（对比旧版方案 B「对话提供」，彻底消除 LLM 幻觉 novel_id 的风险）。

用法：
    python examples/11_narration_client.py                     # 真实 wukong 数据，biography 唐僧
    python examples/11_narration_client.py --subject 孙悟空      # 指定主体
    python examples/11_narration_client.py --task-type chapter_explanation  # 其他解说类型
    python examples/11_narration_client.py --fixture           # 虚构 fixture（林舟/沈岚）回归测试
"""

import importlib.util
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from deerflow_simple import SimpleClient, SimpleConfig
from deerflow_simple.narration import build_generate_narration_tool

# 复用 10_narration.py 的 build_fixture（Python 模块名不能以数字开头，用 importlib 动态加载）
def _load_build_fixture():
    spec = importlib.util.spec_from_file_location(
        "narration_fixture", str(Path(__file__).resolve().parent / "10_narration.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.build_fixture


build_fixture = _load_build_fixture()

SKILLS_DIR = str(Path(__file__).resolve().parent / "skills")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="解说词 · SimpleClient 端到端测试")
    parser.add_argument(
        "--novel-id",
        default="55fa54e9abf04ed88da8b3abf9ba3993",
        help="小说空间 id（默认为真实 wukong 数据目录）",
    )
    parser.add_argument("--subject", default="唐僧", help="传记/设定/感情线的主体名称")
    parser.add_argument(
        "--task-type",
        default="biography",
        help="解说类型（biography/chapter_explanation/faction_landscape/worldbuilding/emotional_arc）",
    )
    parser.add_argument(
        "--fixture",
        action="store_true",
        help="改用虚构 fixture（林舟/沈岚）回归测试；默认用真实 wukong 数据",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("解说词 · SimpleClient 端到端测试")
    print("=" * 60)

    # 1. 确定 workspace 与索引树来源
    #    真实数据模式：用默认 .deerflow_simple/workspace（DS_HOME 已配置），不构造 fixture。
    #    fixture 模式：构造临时 workspace + 虚构索引树（回归完整链路，固定林舟/沈岚）。
    if args.fixture:
        novel_id = "asdafd454da6df"
        subject = "林舟"
        workspace = Path(tempfile.mkdtemp()) / "workspace"
        space_root = workspace / novel_id
        index_root = space_root / "novel"
        build_fixture(index_root)
        sandbox_workspace = str(workspace)
        print(f"\n[1] fixture 模式：索引树已构造 -> {index_root}")
    else:
        novel_id = args.novel_id
        subject = args.subject
        sandbox_workspace = None  # 默认 .deerflow_simple/workspace（真实数据）
        print(f"\n[1] 真实数据模式：使用默认 workspace .deerflow_simple/workspace/{novel_id}")

    # 2. 配置：sandbox_workspace 决定 workspace_path（resolve_novel_root 的根）
    config = SimpleConfig(
        sandbox_enabled=False,      # 聚焦验证 generate_narration，关掉通用沙箱
        subagents_enabled=False,
        summarization_enabled=False,
        memory_enabled=False,
        sandbox_workspace=sandbox_workspace,
        recursion_limit=9999,       # 长任务：LangGraph 递归上限
    )

    # 3. 构建 generate_narration 工具，挂进 lead_agent 的 extra_tools
    gen_tool = build_generate_narration_tool(config, skills_dir=SKILLS_DIR)
    client = SimpleClient(config, extra_tools=[gen_tool])

    # 4. 下发任务（novel_id 由代码通过 client.chat 传入，prompt 里不含 novel_id）
    prompt = (
        "请调用 generate_narration 工具，生成一篇解说词。\n"
        f"task_type={args.task_type}\n"
        f"subject={subject}"
    )
    print(f"\n[2] 下发任务（novel_id 由代码注入，不出现在 prompt）:\n{prompt}\n")
    print(f"[2b] 代码注入 novel_id = {novel_id}\n")

    try:
        reply = client.chat(
            prompt,
            thread_id=f"narration-test-{novel_id[:8]}",
            novel_id=novel_id,
        )
        print("=" * 60)
        print("lead_agent 最终回复")
        print("=" * 60)
        print(reply)
    finally:
        client.close()


if __name__ == "__main__":
    main()
