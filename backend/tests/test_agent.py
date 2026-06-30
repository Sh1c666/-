"""Orchestrator tests with a fake LLM and fake tools.

These pin down the ReAct-loop *control flow* — masking round-trip, event
sequence, terminal conditions, and the max-steps backstop — without touching
the network or a real model.
"""

from __future__ import annotations

from typing import Any

import pytest

from netpilot import tools as toolreg
from netpilot.agent import orchestrator
from netpilot.tools.base import Severity, ToolResult


# -- fake OpenAI/GLM response objects ----------------------------------------
class _Fn:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class _TC:
    def __init__(self, cid: str, name: str, arguments: str) -> None:
        self.id = cid
        self.type = "function"
        self.function = _Fn(name, arguments)


class _Msg:
    def __init__(self, content: str = "", tool_calls: list | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls


class _Resp:
    def __init__(self, message: _Msg) -> None:
        self.choices = [type("C", (), {"message": message})()]


def _make_chat(rounds: list[_Resp]):
    it = iter(rounds)

    async def fake_chat(messages, tools):  # noqa: ANN001
        try:
            return next(it)
        except StopIteration:
            return _Resp(_Msg(content="（已无更多步骤）"))

    return fake_chat


def _make_dispatch(log: list[tuple[str, dict]]):
    async def fake_dispatch(name: str, args: dict[str, Any]) -> ToolResult:
        log.append((name, args))
        return ToolResult(
            tool=name,
            severity=Severity.OK,
            summary_zh=f"[fake {name}] 参数={args}",
            data={"args": args},
        )

    return fake_dispatch


# --------------------------------------------------------------------------- A
@pytest.mark.asyncio
async def test_full_loop_with_submit_conclusion_and_privacy(monkeypatch):
    # The symptom carries an internal IP; privacy is on by default.
    symptom = "内网 10.0.0.5 的 OA 系统打不开"

    captured: list[tuple[str, dict]] = []
    monkeypatch.setattr(orchestrator, "chat", _make_chat([
        _Resp(_Msg(content="先排查 DNS。", tool_calls=[
            _TC("c1", "dns_lookup", '{"host": "[内网IP-1]"}'),
        ])),
        _Resp(_Msg(tool_calls=[
            _TC("c2", "submit_conclusion", json_conclusion()),
        ])),
    ]))
    monkeypatch.setattr(toolreg, "dispatch", _make_dispatch(captured))

    events = [e async for e in orchestrator.run_diagnosis(symptom)]

    types = [e["type"] for e in events]
    assert types[0] == "meta"
    assert "message" in types
    assert "tool_call" in types and "tool_result" in types
    assert types[-1] == "done"

    # The LLM saw a masked token, but the tool must have run against the REAL IP.
    assert captured[0][0] == "dns_lookup"
    assert captured[0][1]["host"] == "10.0.0.5"

    final = next(e for e in events if e["type"] == "final")
    assert final["is_network_issue"] is True
    assert final["layer"] == "DNS"
    assert "dns_lookup 失败" in final["evidence"]


# --------------------------------------------------------------------------- B
@pytest.mark.asyncio
async def test_terminates_on_plain_text(monkeypatch):
    monkeypatch.setattr(orchestrator, "chat", _make_chat([
        _Resp(_Msg(content="根据现有信息,网络层正常,建议查应用。")),
    ]))
    monkeypatch.setattr(toolreg, "dispatch", _make_dispatch([]))

    events = [e async for e in orchestrator.run_diagnosis("某服务慢")]
    types = [e["type"] for e in events]
    assert "tool_call" not in types
    final = next(e for e in events if e["type"] == "final")
    assert final["text"] == "根据现有信息,网络层正常,建议查应用。"
    assert final["is_network_issue"] is None


# --------------------------------------------------------------------------- C
@pytest.mark.asyncio
async def test_max_steps_backstop(monkeypatch):
    original = orchestrator.runtime.cfg.llm.max_steps
    orchestrator.runtime.cfg.llm.max_steps = 2
    try:
        # Always calls a diagnostic tool, never concludes.
        def looping():
            while True:
                yield _Resp(_Msg(tool_calls=[_TC("c", "dns_lookup", '{"host":"example.com"}')]))

        gen = looping()

        async def fake_chat(messages, tools):  # noqa: ANN001
            return next(gen)

        monkeypatch.setattr(orchestrator, "chat", fake_chat)
        monkeypatch.setattr(toolreg, "dispatch", _make_dispatch([]))

        events = [e async for e in orchestrator.run_diagnosis("x")]
        final = next(e for e in events if e["type"] == "final")
        assert "步数" in final["root_cause"]
        # exactly max_steps tool calls before the backstop fires
        assert sum(1 for e in events if e["type"] == "tool_call") == 2
    finally:
        orchestrator.runtime.cfg.llm.max_steps = original


def json_conclusion() -> str:
    import json

    return json.dumps({
        "is_network_issue": True,
        "layer": "DNS",
        "root_cause": "内网 DNS 解析异常",
        "evidence": ["dns_lookup 失败"],
        "recommendation": "检查本机/上游 DNS 配置",
        "confidence": "high",
    })
