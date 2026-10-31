"""10 解说词检索测试 —— 测试 NarrationAgent 检索小说索引树的过程。

本测试用「虚构样例」（设计文档 novel-index-templates.md §12：林舟 / 沈岚 / 青竹书院 /
听风术）动态构造一个最小但完整的索引树，分两层验证「检索」：

1. 确定性工具链测试（默认跑，不调 LLM，快、可重复）
   —— 验证 7 个只读工具能正确检索索引树：load_manifest / load_task_routes /
      search_name / load_entity / load_chapter_ledger / read_file / ls
2. 端到端检索测试（--e2e，调 LLM）
   —— 让 NarrationAgent 自主走一遍「名字消歧 → 下钻检索 → 原文核验」流程

用法：
    python examples/10_narration.py          # 只跑确定性测试
    python examples/10_narration.py --e2e     # 追加端到端检索（需配置 DS_API_KEY）
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from deerflow_simple import SimpleConfig
from deerflow_simple.narration import build_narration_tools, build_narration_agent

SKILLS_DIR = str(Path(__file__).resolve().parent / "skills")


# ---------------------------------------------------------------------------
# fixture 构造（虚构样例，符合 novel-index-templates.md v2.0）
# ---------------------------------------------------------------------------

def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def build_fixture(root: Path | None = None) -> Path:
    """构造一个最小但完整的索引树，返回其根路径（索引树根）。

    Args:
        root: 索引树根目录（index root，如 workspace/{novel_id}/novel，与
            novel-index-creator 约定一致）；None 时用临时目录（用后即弃）。

    注意：这里 root 是「索引树根」而非「小说空间根」，manifest.json 与各主题索引
    都建在 root 下。调用方（如 11_narration_client.py）应传入 space_root/novel。
    """
    if root is None:
        root = Path(tempfile.mkdtemp()) / "novel"
    else:
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)

    # manifest.json
    _write_json(root / "manifest.json", {
        "schema_version": "2.0", "novel_id": "novel-example", "id": "manifest",
        "kind": "manifest", "revision": 1, "safe_through": 0,
        "title": "示例小说", "author": None, "language": "zh-CN",
        "source_version": "source-v1",
        "catalog_ref": {"path": "navigation/catalog.json", "record_id": "idx-catalog"},
        "name_index_ref": {"path": "navigation/names/index.json", "record_id": "idx-names"},
        "task_routes_ref": {"path": "navigation/task-routes.json", "record_id": "task-routes"},
        "chapter_ledger_directory": "ledger/chapters/",
        "published_through": 1, "retrieval_guide_path": "retrieval-guide.md",
    })

    # navigation/catalog.json
    _write_json(root / "navigation" / "catalog.json", {
        "schema_version": "2.0", "novel_id": "novel-example", "id": "idx-catalog",
        "kind": "index", "revision": 1, "safe_through": 0, "title": "主题导航",
        "entries": [
            {"target": {"path": "characters/index.json", "record_id": "idx-characters"},
             "title": "人物传记", "summary": "按人物和经历阶段定位材料", "tags": ["character"]},
            {"target": {"path": "events/index.json", "record_id": "idx-events"},
             "title": "共享事件", "summary": "查询跨主题引用的剧情事件", "tags": ["event"]},
        ],
    })

    # navigation/task-routes.json（五类路由，biography 用全，其余简写）
    _write_json(root / "navigation" / "task-routes.json", {
        "schema_version": "2.0", "novel_id": "novel-example", "id": "task-routes",
        "kind": "task_routes", "revision": 1, "safe_through": 0,
        "defaults": {"max_context_tokens": 12000, "task_token_budget": 32000},
        "routes": [
            {"task_type": "chapter_explanation", "requires_subject": False,
             "required_materials": ["chapter_summary", "event", "source"],
             "optional_materials": ["arc_summary"], "stop_when": "主要行动、转折和结果已有依据。"},
            {"task_type": "biography", "requires_subject": True,
             "entry_refs": [
                 {"path": "navigation/names/index.json", "record_id": "idx-names"},
                 {"path": "characters/index.json", "record_id": "idx-characters"}],
             "required_materials": ["entity_index", "character_stage", "event", "source"],
             "optional_materials": ["relationship"], "stop_when": "关键选择、变化与转折均有依据。"},
            {"task_type": "faction_landscape", "requires_subject": False,
             "required_materials": ["faction_landscape", "event"], "stop_when": "势力与冲突变化有依据。"},
            {"task_type": "worldbuilding", "requires_subject": True,
             "required_materials": ["setting", "source"], "stop_when": "定义、条件、限制已检查。"},
            {"task_type": "emotional_arc", "requires_subject": True,
             "required_materials": ["emotional_index", "event"], "stop_when": "互动与转折有依据。"},
        ],
    })

    # navigation/names/index.json + part-0001.json
    _write_json(root / "navigation" / "names" / "index.json", {
        "schema_version": "2.0", "novel_id": "novel-example", "id": "idx-names",
        "kind": "name_catalog", "revision": 1, "safe_through": 0,
        "normalization": "nfkc_trim", "match_mode": "exact",
        "shard_refs": [{"path": "navigation/names/part-0001.json", "record_id": "names-part-0001"}],
    })
    _write_json(root / "navigation" / "names" / "part-0001.json", {
        "schema_version": "2.0", "novel_id": "novel-example", "id": "names-part-0001",
        "kind": "name_lookup", "revision": 1, "safe_through": 1,
        "entries": [
            {"normalized_name": "林舟", "matches": [
                {"surface": "林舟", "entity_ref": {"path": "characters/char-0001/index.json", "record_id": "char-0001"},
                 "entity_type": "character", "name_type": "name"}]},
            {"normalized_name": "沈岚", "matches": [
                {"surface": "沈岚", "entity_ref": {"path": "characters/char-0002/index.json", "record_id": "char-0002"},
                 "entity_type": "character", "name_type": "name"}]},
        ],
    })

    # characters：林舟（char-0001）与沈岚（char-0002）
    for cid, label, title, summary in [
        ("char-0001", "林舟", "林舟·溪边初见", "林舟在溪边遇到沈岚，得到听风术口诀，并向沈岚道谢。"),
        ("char-0002", "沈岚", "沈岚·溪边初见", "沈岚在溪边把听风术口诀交给林舟，自称来自青竹书院。"),
    ]:
        _write_json(root / "characters" / cid / "index.json", {
            "schema_version": "2.0", "novel_id": "novel-example", "id": cid,
            "kind": "entity_index", "revision": 1, "safe_through": 1,
            "entity_type": "character", "label": label,
            "entries": [{"target": {"path": f"characters/{cid}/stages/stage-001.md",
                                     "record_id": f"doc-{cid}-stage-001"},
                         "kind": "character_stage", "title": title, "summary": summary}],
        })
        stage_file = root / "characters" / cid / "stages" / "stage-001.md"
        stage_file.parent.mkdir(parents=True, exist_ok=True)
        stage_file.write_text(
            f"---\nschema_version: \"2.0\"\nnovel_id: novel-example\nid: doc-{cid}-stage-001\n"
            f"kind: character_stage\nrevision: 1\nsafe_through: 1\ntitle: {title}\nas_of: 1\n---\n\n{summary}\n",
            encoding="utf-8",
        )

    # events/block-0001.json：ev-0001 + claim-0001~0004（§6.2）
    _write_json(root / "events" / "block-0001.json", {
        "schema_version": "2.0", "novel_id": "novel-example", "id": "events-block-0001",
        "kind": "event_collection", "revision": 1, "safe_through": 1,
        "events": [{
            "id": "ev-0001", "kind": "event", "title": "溪边交付口诀",
            "introduced_at": 1, "safe_through": 1,
            "updates": [{
                "id": "update-0001", "chapter_ranges": [{"start": 1, "end": 1}],
                "revealed_at": 1, "status": "completed", "story_time": None,
                "summary": "沈岚交付口诀并说明静心要求，林舟向她道谢。",
                "claims": [
                    {"id": "claim-0001", "text": "沈岚把听风术的口诀交给林舟。", "certainty": "explicit",
                     "attributed_to_ref": None, "revealed_at": 1,
                     "source_refs": [{"path": "source/vol-001/ch-000001.txt", "chapter_id": "ch-000001", "chapter_order": 1}]},
                    {"id": "claim-0002", "text": "按沈岚的说法，练习听风术需要先静心。", "certainty": "reported",
                     "attributed_to_ref": {"path": "characters/char-0002/index.json", "record_id": "char-0002"},
                     "revealed_at": 1,
                     "source_refs": [{"path": "source/vol-001/ch-000001.txt", "chapter_id": "ch-000001",
                                      "chapter_order": 1, "anchor": "先静心，才听得清。"}]},
                    {"id": "claim-0003", "text": "沈岚自称来自青竹书院。", "certainty": "reported",
                     "attributed_to_ref": {"path": "characters/char-0002/index.json", "record_id": "char-0002"},
                     "revealed_at": 1,
                     "source_refs": [{"path": "source/vol-001/ch-000001.txt", "chapter_id": "ch-000001",
                                      "chapter_order": 1, "anchor": "我来自青竹书院。"}]},
                    {"id": "claim-0004", "text": "林舟向沈岚道谢。", "certainty": "explicit",
                     "attributed_to_ref": None, "revealed_at": 1,
                     "source_refs": [{"path": "source/vol-001/ch-000001.txt", "chapter_id": "ch-000001", "chapter_order": 1}]},
                ],
            }],
        }],
    })

    # ledger/chapters/ch-000001.json
    _write_json(root / "ledger" / "chapters" / "ch-000001.json", {
        "schema_version": "2.0", "novel_id": "novel-example", "id": "ledger-ch-000001",
        "kind": "chapter_ledger", "revision": 1, "chapter_id": "ch-000001", "chapter_order": 1,
        "summary": "林舟得到听风术口诀，沈岚自称来自青竹书院。",
        "claims": [
            {"id": "claim-0001", "text": "沈岚把听风术的口诀交给林舟。"},
            {"id": "claim-0003", "text": "沈岚自称来自青竹书院。"},
        ],
    })

    # source/vol-001/ch-000001.txt（原文）
    source_file = root / "source" / "vol-001" / "ch-000001.txt"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text(
        "溪边。沈岚把听风术的口诀交给林舟，说：\u201c先静心，才听得清。\u201d\n"
        "林舟接过口诀，道：\u201c多谢姑娘。\u201d\n"
        "沈岚又说：\u201c我来自青竹书院。\u201d\n",
        encoding="utf-8",
    )

    return root


# ---------------------------------------------------------------------------
# 确定性工具链测试（不调 LLM）
# ---------------------------------------------------------------------------

def test_tools(root: Path) -> int:
    """逐个验证 7 个只读工具能正确检索 fixture。返回失败数。"""
    config = SimpleConfig(sandbox_enabled=False, subagents_enabled=False)
    tm = {t.name: t for t in build_narration_tools(str(root), config)}
    failures = 0

    def check(name: str, cond: bool, detail: str):
        nonlocal failures
        mark = "PASS" if cond else "FAIL"
        if not cond:
            failures += 1
        print(f"  [{mark}] {name}: {detail}")

    # 1. load_manifest
    manifest = tm["load_manifest"].invoke({})
    check("load_manifest", "published_through" in manifest and "示例小说" in manifest,
          "读 manifest.json，拿到 published_through 与标题")

    # 2. load_task_routes
    routes = tm["load_task_routes"].invoke({"task_type": "biography"})
    check("load_task_routes", "character_stage" in routes and "biography" in routes,
          "读 task-routes.json，拿到 biography 路由的必读材料")
    miss = tm["load_task_routes"].invoke({"task_type": "不存在"})
    check("load_task_routes(miss)", "未找到" in miss, "未命中路由返回友好提示")

    # 3. search_name 精确 + 模糊
    exact = json.loads(tm["search_name"].invoke({"name": "林舟"}))
    check("search_name(精确)", exact["status"] == "unique"
          and exact["matches"][0]["entity_ref"]["record_id"] == "char-0001",
          "「林舟」精确命中 char-0001")
    fuzzy = json.loads(tm["search_name"].invoke({"name": "林舟同学"}))
    check("search_name(模糊)", fuzzy["status"] in ("fuzzy", "unique"),
          "「林舟同学」走模糊/子串层")

    # 4. load_entity（record_id 形式，走名字索引定位）
    entity = tm["load_entity"].invoke({"ref": "char-0001"})
    check("load_entity", "char-0001" in entity and "溪边初见" in entity,
          "读人物入口 index.json + 阶段摘要 stages/*.md")

    # 5. load_chapter_ledger
    ledger = tm["load_chapter_ledger"].invoke({"chapter_id": "ch-000001"})
    check("load_chapter_ledger", "claim-0001" in ledger,
          "读 ledger/chapters/ch-000001.json 的 claims")

    # 6. read_file（读原文）
    source = tm["read_file"].invoke({"path": "source/vol-001/ch-000001.txt"})
    check("read_file(原文)", "听风术" in source and "青竹书院" in source,
          "回读原文 source/vol-001/ch-000001.txt 核验")

    # 7. ls
    listing = tm["ls"].invoke({"path": "."})
    check("ls", "manifest.json" in listing and "navigation" in listing,
          "列出索引树根目录")

    return failures


# ---------------------------------------------------------------------------
# 端到端检索测试（调 LLM）
# ---------------------------------------------------------------------------

def test_agent(root: Path) -> None:
    """让 NarrationAgent 自主检索并生成一篇人物传记解说。"""
    from langchain_core.messages import HumanMessage

    config = SimpleConfig(sandbox_enabled=False, subagents_enabled=False)
    print("\n[端到端] 装配 NarrationAgent 并发起 biography 检索 ...")
    agent = build_narration_agent(config, str(root), skills_dir=SKILLS_DIR)

    prompt = (
        "请生成解说词。task_type=biography\n"
        "subject=林舟\n"
        "output_language=zh-CN\n"
        "请严格按你的 SKILL.md 主流程执行。"
    )
    result = agent.invoke({"messages": [HumanMessage(content=prompt)]})
    messages = result.get("messages", [])
    draft = ""
    if messages:
        last = messages[-1]
        draft = getattr(last, "content", "")
        if not isinstance(draft, str):
            draft = str(draft)
    print("\n" + "=" * 60)
    print("解说稿（节选）")
    print("=" * 60)
    print(draft[:1500])
    if len(draft) > 1500:
        print("...（截断，全文过长）")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    run_e2e = "--e2e" in sys.argv

    print("=" * 60)
    print("解说词检索测试")
    print("=" * 60)

    root = build_fixture()
    print(f"\n[fixture] 已构造最小索引树 -> {root}")

    print("\n[1/2] 确定性工具链测试（不调 LLM）")
    failures = test_tools(root)
    if failures == 0:
        print("\n确定性工具链测试：全部通过 ✔")
    else:
        print(f"\n确定性工具链测试：{failures} 项失败 ✘")

    if run_e2e:
        print("\n[2/2] 端到端检索测试（调 LLM）")
        try:
            test_agent(root)
        except Exception as e:  # noqa: BLE001
            print(f"\n端到端测试失败（请确认 DS_API_KEY / DS_BASE_URL 已配置）: {e}")
    else:
        print("\n[2/2] 端到端检索测试：跳过（加 --e2e 启用，需配置 DS_API_KEY）")


if __name__ == "__main__":
    main()
