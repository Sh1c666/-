"""Tool registry — the catalog of diagnostic capabilities offered to the agent.

Adding a new diagnostic is a two-step process:

1. Subclass :class:`~netpilot.tools.base.Tool` and implement ``run``.
2. Register an instance in :data:`_REGISTRY` below.

The OpenAI/GLM ``tools`` schema, dispatch, and UI metadata are then derived
automatically — no other wiring needed.
"""

from __future__ import annotations

from typing import Any

from .base import Severity, Tool, ToolResult
from .dns import DnsLookupTool
from .httpprobe import HttpProbeTool
from .kb import KbSearchTool
from .localcheck import LocalCheckTool
from .ping import IcmpPingTool, TcpPingTool
from .portscan import PortScanTool
from .tls import TlsInspectTool
from .traceroute import TracerouteTool

# Ordered registry — order is also the suggested diagnostic order shown to the LLM.
_REGISTRY: dict[str, Tool] = {
    tool.name: tool
    for tool in [
        DnsLookupTool(),
        IcmpPingTool(),
        TcpPingTool(),
        TracerouteTool(),
        PortScanTool(),
        TlsInspectTool(),
        HttpProbeTool(),
        LocalCheckTool(),
        KbSearchTool(),
    ]
}


def all_tools() -> dict[str, Tool]:
    return dict(_REGISTRY)


def tool_names() -> list[str]:
    return list(_REGISTRY.keys())


def get_tool(name: str) -> Tool | None:
    return _REGISTRY.get(name)


def tool_schemas() -> list[dict[str, Any]]:
    """OpenAI/GLM-compatible ``tools`` payload for the function-calling API."""
    return [t.openai_schema() for t in _REGISTRY.values()]


async def dispatch(name: str, arguments: dict[str, Any]) -> ToolResult:
    """Run a tool by name. Returns a failed ToolResult if unknown/invalid."""
    tool = _REGISTRY.get(name)
    if tool is None:
        return ToolResult(
            tool=name, ok=False, severity=Severity.INFO, error=f"未知工具: {name}"
        )
    try:
        return await tool.run(**arguments)
    except Exception as exc:  # noqa: BLE001 — tools must never crash the agent loop
        return ToolResult(tool=name, ok=False, error=f"{type(exc).__name__}: {exc}")


__all__ = [
    "Tool",
    "ToolResult",
    "Severity",
    "all_tools",
    "tool_names",
    "get_tool",
    "tool_schemas",
    "dispatch",
]
