"""Agent orchestrator — the ReAct loop that drives a diagnosis.

Per run it:

* masks the user's symptom (and any internal IPs) before the LLM ever sees it,
* asks the LLM which tool to call next,
* **un-masks the tool arguments** so the diagnostic runs against real hosts,
* runs the tool, then **re-masks** its structured output before feeding it back,
* streams every step to the UI as SSE events (in real, unmasked form for the
  operator), and
* terminates either on a ``submit_conclusion`` call or when the LLM stops
  calling tools — with a hard ``max_steps`` backstop.

The masking discipline is what makes the privacy story real: the cloud model
only ever sees opaque tokens, while the local operator always sees real IPs.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from .. import tools as toolreg
from ..config import runtime
from ..core.kb import retriever
from ..core.privacy import PrivacyMask
from . import events as E
from .llm_client import LLMError, chat
from .prompts import SYSTEM_PROMPT, build_tools

# Layers considered "the network" for the high-level verdict.
_NETWORK_LAYERS = {
    "网络连通性(链路/丢包)",
    "路径(路由/中间设备)",
    "端口/防火墙",
    "DNS",
    "TLS/证书",
}

# Some weaker models (e.g. glm-4-flash) append a raw tool-call JSON object
# (`{"index":0,"finish_reason":"tool_calls","delta":...}`) onto their text
# content. Strip anything from the first such leaked object to end-of-string.
_LEAKED_TOOLCALL_RE = re.compile(
    r'\{(?:"index":\d+|"finish_reason":|"delta":|"tool_calls":|"role":"assistant")'
)


def _sanitize_content(content: str) -> str:
    m = _LEAKED_TOOLCALL_RE.search(content)
    if m:
        content = content[: m.start()].rstrip()
    return content


def _walk(obj: Any, fn) -> Any:
    if isinstance(obj, str):
        return fn(obj)
    if isinstance(obj, list):
        return [_walk(x, fn) for x in obj]
    if isinstance(obj, dict):
        return {k: _walk(v, fn) for k, v in obj.items()}
    return obj


def _kb_context(query: str, k: int = 2) -> str:
    """Best-effort: append top-k relevant KB snippets to ground the agent."""
    try:
        hits = retriever.search(query, k=k)
    except Exception:  # noqa: BLE001 — KB must never break a diagnosis
        return ""
    if not hits:
        return ""
    lines = [f"- {c.title}({c.source}):{c.text[:180]}" for c, _ in hits]
    return "\n\n# 相关知识参考(来自本地知识库,仅供参考)\n" + "\n".join(lines)


def _parse_args(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        out = json.loads(raw)
        return out if isinstance(out, dict) else {}
    except json.JSONDecodeError:
        return {}


async def run_diagnosis(
    symptom: str,
    context: dict[str, Any] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Run one diagnosis and yield SSE event dicts."""
    session_id = uuid.uuid4().hex[:12]
    started = time.perf_counter()
    masker = PrivacyMask()
    privacy_on = runtime.snapshot().privacy.mask_internal_ips

    def to_llm(text: str) -> str:
        return masker.mask(text) if privacy_on else text

    def to_user(text: str) -> str:
        return masker.unmask(text) if privacy_on else text

    # ---- opening event ----------------------------------------------------
    yield {"type": E.META,
           "session_id": session_id,
           "symptom": symptom,
           "context": context or {},
           "masked": privacy_on}

    user_blob = to_llm(symptom)
    if context:
        user_blob += "\n[补充上下文] " + to_llm(json.dumps(context, ensure_ascii=False))

    # Ground the agent with relevant KB entries (local lexical retrieval).
    system_content = SYSTEM_PROMPT + _kb_context(symptom)

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_blob},
    ]
    tools_payload = build_tools(toolreg.tool_schemas())
    max_steps = runtime.snapshot().llm.max_steps
    steps = 0

    try:
        while True:
            if steps >= max_steps:
                yield {"type": E.FINAL,
                       "is_network_issue": None,
                       "layer": "未确定",
                       "root_cause": "已达到最大排查步数,未能给出明确结论。",
                       "evidence": [],
                       "recommendation": "建议人工介入,或调大步数上限后重试。",
                       "confidence": "low",
                       "text": "已达到最大排查步数上限,请人工复核以上证据。"}
                break

            # ---- one LLM round -------------------------------------------
            try:
                resp = await chat(messages, tools_payload)
            except LLMError as exc:
                yield {"type": E.ERROR, "message": str(exc)}
                break

            choice = resp.choices[0].message
            content = _sanitize_content(getattr(choice, "content", None) or "")
            tool_calls = getattr(choice, "tool_calls", None) or []

            if content.strip():
                yield {"type": E.MESSAGE, "role": "assistant", "text": to_user(content)}

            if not tool_calls:
                # No tool call ⇒ the model is giving its final answer as text.
                yield {"type": E.FINAL,
                       "is_network_issue": None,
                       "layer": "未结构化",
                       "root_cause": "",
                       "evidence": [],
                       "recommendation": "",
                       "confidence": None,
                       "text": to_user(content)}
                break

            # record the assistant turn (kept in masked space)
            assistant_entry: dict[str, Any] = {
                "role": "assistant",
                "content": content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments or "{}",
                        },
                    }
                    for tc in tool_calls
                ],
            }
            messages.append(assistant_entry)

            concluded = False
            for tc in tool_calls:
                name = tc.function.name
                raw_args = tc.function.arguments
                args_real = _walk(_parse_args(raw_args), to_user)  # restore real IPs for execution

                # The terminal tool ⇒ finalize with structured fields.
                if name == "submit_conclusion":
                    c = _walk(args_real, to_user)
                    layer = c.get("layer", "未确定")
                    is_net = c.get("is_network_issue")
                    if is_net is None:
                        is_net = layer in _NETWORK_LAYERS
                    yield {"type": E.FINAL,
                           "is_network_issue": bool(is_net),
                           "layer": layer,
                           "root_cause": c.get("root_cause", ""),
                           "evidence": c.get("evidence", []) or [],
                           "recommendation": c.get("recommendation", ""),
                           "confidence": c.get("confidence"),
                           "text": _compose_report(c)}
                    concluded = True
                    break

                # A diagnostic tool call.
                steps += 1
                yield {"type": E.TOOL_CALL, "id": tc.id, "name": name, "arguments": args_real}

                result = await toolreg.dispatch(name, args_real)
                # Show the operator the REAL (unmasked) result.
                yield {
                    "type": E.TOOL_RESULT,
                    "id": tc.id,
                    "tool": result.tool,
                    "severity": result.severity.value,
                    "ok": result.ok,
                    "summary_zh": to_user(result.summary_zh),
                    "data": _walk(result.data, to_user),
                    "duration_ms": round(result.duration_ms, 1),
                    "error": result.error,
                }
                # Feed the LLM a MASKED, compact rendering.
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": to_llm(result.as_llm_content()),
                })

            if concluded:
                break

    except Exception as exc:  # noqa: BLE001 — never let the stream die silently
        yield {"type": E.ERROR, "message": f"内部错误: {type(exc).__name__}: {exc}"}

    yield {"type": E.DONE, "session_id": session_id,
           "steps": steps, "total_ms": round((time.perf_counter() - started) * 1000, 1)}


def _compose_report(c: dict[str, Any]) -> str:
    """Human-readable rendering of a structured conclusion."""
    parts = []
    flag = "是网络问题" if c.get("is_network_issue") else "非网络问题"
    parts.append(f"结论:{flag}(层级:{c.get('layer', '?')})")
    if c.get("root_cause"):
        parts.append(f"根因:{c['root_cause']}")
    ev = c.get("evidence") or []
    if ev:
        parts.append("证据:\n- " + "\n- ".join(ev))
    if c.get("recommendation"):
        parts.append(f"建议:{c['recommendation']}")
    return "\n\n".join(parts)
