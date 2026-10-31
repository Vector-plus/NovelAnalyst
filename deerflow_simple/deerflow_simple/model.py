"""模型工厂。

对应 DeerFlow 的 `models/factory.py::create_chat_model`，但精简为 OpenAI 兼容
（`langchain_openai.ChatOpenAI`），足以覆盖 OpenAI / DeepSeek / 本地 vLLM 等。
"""

from __future__ import annotations

from langchain_openai import ChatOpenAI

from deerflow_simple.config import ModelSettings, SimpleConfig


def create_chat_model(
    config: SimpleConfig,
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    attach_tracing: bool = False,
) -> ChatOpenAI:
    """根据配置创建一个 OpenAI 兼容的聊天模型。

    `attach_tracing` 对应 DeerFlow 的同名参数：在 graph root 统一挂 tracing
    callback 时，模型内部不再单独挂（避免重复 span）。精简版中 LangSmith 由
    langchain 内置 env 驱动自动集成，此处仅保留设计占位。

    `max_tokens` 是任务级单次输出 token 上限（含 reasoning 模型的「思考」与正式
    内容），None 表示不设限（用模型默认）。与 temperature 不同，它不放 ModelSettings
    —— 不同任务的输出量级差异大（路由任务小、结构化 JSON 提取大），应由调用方
    （如 index_builder 各子 agent）按任务类型传入。
    """
    settings: ModelSettings = config.model
    if not settings.api_key:
        raise ValueError(
            "未检测到 API Key。请设置环境变量 DS_API_KEY 或 OPENAI_API_KEY，"
            "或复制 .env.example 为 .env 并在其中填写真实 key。"
        )
    kwargs: dict = {
        "model": settings.model,
        "temperature": temperature if temperature is not None else settings.temperature,
        "api_key": settings.api_key,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if settings.base_url:
        kwargs["base_url"] = settings.base_url
    return ChatOpenAI(**kwargs)
