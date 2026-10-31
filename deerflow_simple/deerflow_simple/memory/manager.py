"""SimpleMemoryManager —— 长期记忆管理器（deermem 的极简版）。

参考 DeerFlow deermem 的核心机制并大幅简化，只保留六点：

- 结构化抽取：LLM 输出 JSON，含 content / category / confidence（对应 fact_extraction.yaml）。
- 纯寒暄过滤：丢弃「嗯 / 好的 / 谢谢」等确认语，避免触发无意义抽取（对应 filter_trivial）。
- 置信度阈值：confidence 低于阈值的事实不存储（对应 fact_confidence_threshold）。
- 去重：内容归一化后精确去重 + 包含关系合并（对应 fact_dedup）。
- 容量驱逐：超出 max_facts 时按 confidence 降序保留（对应 eviction 的 confidence 策略）。
- 注入裁剪：get_context 按 confidence 降序取前 N 条（对应 max_injection_tokens 的条数化简化）。

事实结构：`{id, content, category, confidence, created_at}`；旧格式 `{id, content, created_at}`
在加载时自动补默认值（category="context"，confidence=0.5），保证向后兼容。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage

from deerflow_simple.config import SimpleConfig

_manager: "SimpleMemoryManager | None" = None


def get_memory_manager(config: SimpleConfig) -> "SimpleMemoryManager":
    """进程内单例。"""
    global _manager
    if _manager is None:
        _manager = SimpleMemoryManager(config)
    return _manager


# 纯寒暄/确认语，不携带长期价值，跳过抽取（对应 deermem 的 filter_trivial）。
_TRIVIAL_RE = re.compile(
    r"^(嗯+|好的|好|ok|okay|谢谢|多谢|thanks|thank you|收到|明白|知道了|了解|fine|got it|"
    r"你好|您好|hi|hello|在吗|在不在)[\s\.,。，!！?？~～]*$",
    re.IGNORECASE,
)


def _is_trivial(text: str) -> bool:
    t = text.strip()
    return bool(t) and _TRIVIAL_RE.match(t) is not None


def _filter_conversation(messages: list) -> str:
    """只保留用户输入与最终助手回复，忽略中间 tool 调用，并过滤纯寒暄。"""
    lines = []
    for m in messages:
        if isinstance(m, HumanMessage):
            content = m.content if isinstance(m.content, str) else str(m.content)
            if content.strip() and not _is_trivial(content):
                lines.append(f"用户: {content.strip()}")
        elif isinstance(m, AIMessage) and m.content:
            lines.append(f"助手: {m.content}")
    return "\n".join(lines)


def _to_float(value, default: float = 0.0) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, f))


class SimpleMemoryManager:
    def __init__(self, config: SimpleConfig):
        self._config = config
        self._path = config.memory_path
        self._facts: list[dict] = self._load()

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------
    def _load(self) -> list[dict]:
        if not self._path.exists():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        if not isinstance(data, list):
            return []
        return [self._normalize(f) for f in data if isinstance(f, dict)]

    @staticmethod
    def _normalize(fact: dict) -> dict:
        """规范化一条事实：补全缺失字段（向后兼容旧格式）。"""
        return {
            "id": str(fact.get("id") or uuid4()),
            "content": str(fact.get("content", "")).strip(),
            "category": str(fact.get("category") or "context"),
            "confidence": _to_float(fact.get("confidence"), default=0.5),
            "created_at": str(fact.get("created_at") or datetime.now(timezone.utc).isoformat()),
        }

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._facts, ensure_ascii=False, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------
    # 读
    # ------------------------------------------------------------------
    def get_context(self) -> str:
        """返回注入用的记忆文本：按 confidence 降序，最多 N 条。"""
        if not self._facts:
            return ""
        ranked = sorted(self._facts, key=lambda f: f.get("confidence", 0.0), reverse=True)
        top = ranked[: self._config.memory_injection_max_facts]
        return "\n".join(f"- {f['content']}" for f in top)

    def search(self, query: str) -> str:
        """关键词检索，结果按 confidence 降序。"""
        hits = [f for f in self._facts if query in f["content"]]
        hits.sort(key=lambda f: f.get("confidence", 0.0), reverse=True)
        return "\n".join(f["content"] for f in hits) if hits else "(无匹配记忆)"

    # ------------------------------------------------------------------
    # 写
    # ------------------------------------------------------------------
    def _dedupe_and_add(self, content: str, category: str = "context", confidence: float = 0.9) -> str:
        """去重后新增一条事实；容量超限时按 confidence 驱逐。

        返回 "added"（新增）/ "duplicate"（重复或合并）/ "rejected"（低置信度被拒）。
        """
        content = content.strip()
        if not content or confidence < self._config.memory_confidence_threshold:
            return "rejected"

        now = datetime.now(timezone.utc).isoformat()
        # 精确去重（归一化后相同）
        for f in self._facts:
            if f["content"].strip() == content:
                if f["confidence"] < confidence:
                    f["confidence"] = confidence
                return "duplicate"
        # 包含关系去重：一条是另一条的子串视为同一事实，保留更长的、合并置信度
        for f in self._facts:
            fc = f["content"].strip()
            if not fc:
                continue
            if content in fc:
                if f["confidence"] < confidence:
                    f["confidence"] = confidence
                return "duplicate"
            if fc in content:
                f["content"] = content
                if f["confidence"] < confidence:
                    f["confidence"] = confidence
                return "duplicate"

        self._facts.append(
            {
                "id": str(uuid4()),
                "content": content,
                "category": category,
                "confidence": confidence,
                "created_at": now,
            }
        )
        self._evict()
        return "added"

    def _evict(self) -> None:
        """超出 max_facts 时按 confidence 降序保留（deermem confidence 驱逐策略）。"""
        if len(self._facts) <= self._config.memory_max_facts:
            return
        self._facts.sort(key=lambda f: f.get("confidence", 0.0), reverse=True)
        self._facts = self._facts[: self._config.memory_max_facts]

    def add_fact(self, content: str) -> str:
        """手动写入一条事实（工具用），默认高置信度。"""
        content = content.strip()
        if not content:
            return "空内容，未添加。"
        result = self._dedupe_and_add(content, category="context", confidence=0.9)
        self._save()
        if result == "added":
            return f"已记住：{content}"
        return f"未重复添加（已存在或置信度过低）：{content}"

    def add(self, thread_id: str, messages: list) -> None:
        """从一轮对话中抽取事实（LLM），结构化 + 阈值 + 去重 + 驱逐后写入。"""
        conversation = _filter_conversation(messages)
        if not conversation.strip():
            return
        extracted = self._extract(conversation)
        if not extracted:
            return
        for item in extracted:
            self._dedupe_and_add(
                item["content"],
                category=item.get("category", "context"),
                confidence=item.get("confidence", 0.5),
            )
        self._save()

    def _extract(self, conversation: str) -> list[dict]:
        """LLM 结构化抽取事实（参考 deermem fact_extraction.yaml），输出 JSON。"""
        from deerflow_simple.model import create_chat_model

        model = create_chat_model(self._config, temperature=0.0)
        prompt = (
            "从下面的对话中抽取关于用户的、值得长期记住的稳定事实。\n"
            "只抽取明确、具体、可复用的信息（身份、偏好、目标、纠错、行为习惯等）；\n"
            "跳过寒暄、一次性任务、临时状态等无长期价值的内容。\n\n"
            "按如下 JSON 格式输出：\n"
            '{"facts": [{"content": "...", "category": "preference|knowledge|context|behavior|cognitive|goal|correction", "confidence": 0.0-1.0}]}\n\n'
            "category 含义：\n"
            "- preference: 用户偏好（喜好/风格/工具）\n"
            "- knowledge: 用户擅长或了解的领域\n"
            "- context: 背景信息（地点/职业/项目）\n"
            "- behavior: 行为模式\n"
            "- cognitive: 稳定的思考/协作习惯\n"
            "- goal: 用户目标\n"
            "- correction: 明确的纠错或需避免重复的错误\n\n"
            "confidence 反映确定程度：明确陈述 0.9+，隐含 0.6-0.8，模糊/临时 0.5 以下。\n"
            '没有值得记的事实就输出 {"facts": []}。只输出 JSON，不要其它内容。\n\n'
            f"对话：\n{conversation}"
        )
        try:
            resp = model.invoke(prompt)
            text = resp.content if isinstance(resp.content, str) else str(resp.content)
        except Exception:
            return []
        return self._parse_facts(text)

    @staticmethod
    def _parse_facts(text: str) -> list[dict]:
        """从 LLM 输出中解析 facts 数组（容错：剥离可能的 markdown 代码围栏）。"""
        text = text.strip()
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []
        facts = data.get("facts") if isinstance(data, dict) else None
        if not isinstance(facts, list):
            return []
        result = []
        for f in facts:
            if not isinstance(f, dict):
                continue
            content = str(f.get("content", "")).strip()
            if not content:
                continue
            result.append(
                {
                    "content": content,
                    "category": str(f.get("category") or "context"),
                    "confidence": _to_float(f.get("confidence"), default=0.0),
                }
            )
        return result
