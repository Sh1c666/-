"""LLM client — any OpenAI-compatible endpoint (DeepSeek / GLM / OpenAI / Ollama).

The provider exposes an OpenAI-compatible ``/chat/completions`` endpoint, so we
reuse the official ``openai`` SDK pointed at ``base_url`` and let the model's
function-calling drive the agent. The client is rebuilt from the live runtime
config on every call, so changes made in the UI (key / model / temperature)
take effect immediately.

Note: the model must support function/tool calling. ``deepseek-chat`` and
``glm-4.5`` do; ``deepseek-reasoner`` (R1) does not and will break the loop.
"""

from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI

from ..config import runtime


class LLMError(Exception):
    """Raised when the LLM is not usable (missing key, transport error, ...)."""


def _client() -> AsyncOpenAI:
    cfg = runtime.snapshot().llm
    if not cfg.api_key:
        raise LLMError(
            "未配置 LLM API Key。请在 UI 设置中填入,或在 backend/.env 设置 NETPILOT_LLM_API_KEY。"
        )
    return AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url)


async def chat(messages: list[dict], tools: list[dict]) -> Any:
    """One function-calling round. Returns the raw chat completion response."""
    cfg = runtime.snapshot().llm
    client = _client()
    try:
        return await client.chat.completions.create(
            model=cfg.model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
        )
    except Exception as exc:  # noqa: BLE001 — surface a clean error to the orchestrator
        raise LLMError(f"{type(exc).__name__}: {exc}") from exc


__all__ = ["chat", "LLMError"]
