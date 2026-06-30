"""LLM client — talks to either an OpenAI-compatible or an Anthropic-compatible
endpoint, chosen at runtime via ``LLMConfig.protocol``.

Two transports, one shape:

* ``protocol == "openai"`` (default) — the official ``openai`` SDK pointed at
  ``base_url``. Works with DeepSeek / GLM (paas/v4) / OpenAI / Ollama.
* ``protocol == "anthropic"`` — the official ``anthropic`` SDK pointed at an
  Anthropic-protocol endpoint (e.g. BigModel's ``/api/anthropic``, which serves
  ``glm-4.6`` / ``glm-5.2`` under their Claude-compatible subscription — the v4
  endpoint returns 1113 for those models, so this path exists for that case).

Both paths return an object with the same attribute shape —
``choices[0].message.content`` and
``choices[0].message.tool_calls[i].{id, function.{name, arguments}}`` — so the
orchestrator consumes them identically. Adding the Anthropic path changed
nothing about how a diagnosis runs.

Note: the model must support function/tool calling.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
)

from ..config import runtime

# Fail fast instead of hanging silently when the model endpoint is unreachable.
# The openai SDK's own default is ~10 minutes, which to the user looks like
# "I clicked and nothing happened".
REQUEST_TIMEOUT_S = 60.0


class LLMError(Exception):
    """Raised when the LLM is not usable (missing key, transport error, ...)."""


# ---------------------------------------------------------------------------
# Normalized response shape.
#
# The orchestrator reads ``resp.choices[0].message.content`` and
# ``...tool_calls[i].{id, function.{name, arguments}}``. The OpenAI SDK already
# returns objects with exactly these attributes, so the OpenAI path returns the
# SDK response untouched. The Anthropic path wraps its response into the same
# shim below — keeping the two interchangeable.
@dataclass
class _FunctionCall:
    name: str
    arguments: str


@dataclass
class _ToolCall:
    id: str
    function: _FunctionCall


@dataclass
class _Message:
    content: str | None
    tool_calls: list[_ToolCall] = field(default_factory=list)


@dataclass
class _Choice:
    message: _Message


@dataclass
class _Completion:
    choices: list[_Choice]


def _need_key(cfg) -> None:
    if not cfg.api_key:
        raise LLMError(
            "未配置 LLM API Key。请在 UI 设置中填入,或在 backend/.env 设置 NETPILOT_LLM_API_KEY。"
        )


# ---------------------------------------------------------------------------
# OpenAI-compatible path (unchanged behaviour).
def _client_openai(cfg) -> AsyncOpenAI:
    _need_key(cfg)
    return AsyncOpenAI(
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        timeout=REQUEST_TIMEOUT_S,
        max_retries=1,  # surface failures quickly instead of a long retry backoff
    )


async def _chat_openai(cfg, messages: list[dict], tools: list[dict]) -> Any:
    client = _client_openai(cfg)
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
        raise LLMError(_friendly_openai(exc)) from exc


# ---------------------------------------------------------------------------
# Anthropic-protocol path.
def _to_anthropic_messages(messages: list[dict]) -> tuple[str | None, list[dict]]:
    """Convert the orchestrator's OpenAI-style message list into Anthropic form.

    Differences handled: ``system`` becomes a top-level param (not a message);
    assistant ``tool_calls`` become ``tool_use`` content blocks; consecutive
    ``tool`` results are merged into one ``user`` message with several
    ``tool_result`` blocks (Anthropic rejects interleaved same-role turns).
    """
    system_parts: list[str] = []
    out: list[dict] = []
    for msg in messages:
        role = msg.get("role")
        if role == "system":
            if msg.get("content"):
                system_parts.append(msg["content"])
        elif role == "user":
            out.append({"role": "user", "content": msg.get("content") or ""})
        elif role == "assistant":
            blocks: list[dict] = []
            if msg.get("content"):
                blocks.append({"type": "text", "text": msg["content"]})
            for tc in msg.get("tool_calls") or []:
                fn = tc.get("function", {})
                try:
                    inp = json.loads(fn.get("arguments") or "{}")
                    if not isinstance(inp, dict):
                        inp = {}
                except json.JSONDecodeError:
                    inp = {}
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc.get("id"),
                        "name": fn.get("name"),
                        "input": inp,
                    }
                )
            out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": ""}]})
        elif role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": msg.get("tool_call_id"),
                "content": msg.get("content") or "",
            }
            prev = out[-1] if out else None
            if (
                prev
                and prev["role"] == "user"
                and isinstance(prev["content"], list)
                and prev["content"]
                and all(b.get("type") == "tool_result" for b in prev["content"])
            ):
                prev["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
    system = "\n\n".join(system_parts) if system_parts else None
    return system, out


def _to_anthropic_tools(tools: list[dict]) -> list[dict]:
    """OpenAI tool schema → Anthropic tool schema (``parameters`` → ``input_schema``)."""
    out: list[dict] = []
    for t in tools:
        fn = t.get("function", t)  # OpenAI wraps the spec in {"type":"function","function":{…}}
        out.append(
            {
                "name": fn.get("name"),
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
            }
        )
    return out


async def _chat_anthropic(cfg, messages: list[dict], tools: list[dict]) -> _Completion:
    import anthropic  # lazy: keeps the OpenAI-only path free of this dependency

    _need_key(cfg)
    system, msgs = _to_anthropic_messages(messages)
    try:
        client = anthropic.AsyncAnthropic(
            api_key=cfg.api_key,
            base_url=cfg.base_url,
            timeout=REQUEST_TIMEOUT_S,
            max_retries=1,
        )
        kwargs: dict[str, Any] = dict(
            model=cfg.model,
            messages=msgs,
            tools=_to_anthropic_tools(tools),
            tool_choice={"type": "auto"},
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
        )
        if system:
            kwargs["system"] = system
        resp = await client.messages.create(**kwargs)
    except Exception as exc:  # noqa: BLE001
        raise LLMError(_friendly_anthropic(exc)) from exc

    text_parts: list[str] = []
    tool_calls: list[_ToolCall] = []
    for block in resp.content:
        btype = getattr(block, "type", None)
        if btype == "text":
            text_parts.append(getattr(block, "text", ""))
        elif btype == "tool_use":
            tool_calls.append(
                _ToolCall(
                    id=getattr(block, "id", ""),
                    function=_FunctionCall(
                        name=getattr(block, "name", ""),
                        arguments=json.dumps(
                            getattr(block, "input", {}) or {}, ensure_ascii=False
                        ),
                    ),
                )
            )
    content = "".join(text_parts) if text_parts else None
    return _Completion(choices=[_Choice(message=_Message(content=content, tool_calls=tool_calls))])


# ---------------------------------------------------------------------------
# Public entry — branches on protocol; returns one normalized shape either way.
async def chat(messages: list[dict], tools: list[dict]) -> Any:
    """One function-calling round. Returns a normalized chat completion."""
    cfg = runtime.snapshot().llm
    if cfg.protocol == "anthropic":
        return await _chat_anthropic(cfg, messages, tools)
    return await _chat_openai(cfg, messages, tools)


# ---------------------------------------------------------------------------
# Friendly error translation.
def _friendly_openai(exc: Exception) -> str:
    """Translate openai SDK exceptions into actionable Chinese for the UI."""
    if isinstance(exc, AuthenticationError):
        return "API Key 无效或已过期（401）。请到「设置」检查或重新填写 API Key。"
    if isinstance(exc, APITimeoutError):
        return (
            f"调用模型超时（{REQUEST_TIMEOUT_S:.0f}s 无响应）。可能是网络到模型服务不通，"
            "或服务太慢——检查 Base URL 与网络后重试。"
        )
    if isinstance(exc, APIConnectionError):
        return "无法连接到模型服务。请检查 Base URL 是否正确、当前网络能否访问该地址。"
    if isinstance(exc, RateLimitError):
        return "模型服务限流（429）。请稍后重试，或降低调用频率。"
    if isinstance(exc, BadRequestError):
        return (
            f"模型服务拒绝了请求（400）：{exc}。"
            "常见原因：模型名写错，或该端点/模型不在套餐覆盖内"
            "（如 BigModel 的 paas/v4 端点对高端模型返回 1113 余额不足）。"
        )
    if isinstance(exc, APIStatusError):
        return f"模型服务返回错误（HTTP {exc.status_code}）：{exc}"
    return f"{type(exc).__name__}: {exc}"


def _friendly_anthropic(exc: Exception) -> str:
    """Translate anthropic SDK exceptions into actionable Chinese for the UI."""
    import anthropic as _a

    if isinstance(exc, getattr(_a, "AuthenticationError", ())):
        return "API Key 无效或已过期（401）。请到「设置」检查或重新填写 API Key。"
    if isinstance(exc, getattr(_a, "APITimeoutError", ())):
        return (
            f"调用模型超时（{REQUEST_TIMEOUT_S:.0f}s 无响应）。检查 Base URL 与网络后重试。"
        )
    if isinstance(exc, getattr(_a, "APIConnectionError", ())):
        return (
            "无法连接到模型服务。请检查 Base URL 是否正确（Anthropic 协议，"
            "如 https://open.bigmodel.cn/api/anthropic）、当前网络能否访问该地址。"
        )
    if isinstance(exc, getattr(_a, "RateLimitError", ())):
        return "模型服务限流（429）或余额/资源包不足。请稍后重试，或到 provider 后台确认套餐覆盖。"
    if isinstance(exc, getattr(_a, "BadRequestError", ())):
        return f"模型服务拒绝了请求（400）：{exc}。常见原因：模型名写错、协议与端点不匹配。"
    if isinstance(exc, getattr(_a, "APIStatusError", ())):
        return f"模型服务返回错误（HTTP {getattr(exc, 'status_code', '?')}）：{exc}"
    return f"{type(exc).__name__}: {exc}"


__all__ = ["chat", "LLMError"]
