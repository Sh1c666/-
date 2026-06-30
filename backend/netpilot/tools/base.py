"""Tool layer foundation.

Every diagnostic capability is a :class:`Tool` subclass that:

* declares an OpenAI-compatible ``parameters`` JSON-schema so the LLM can call it
  via function-calling,
* returns a :class:`ToolResult` carrying **structured data** plus a Chinese
  ``summary_zh`` (the "soul field" — a plain-language interpretation that keeps
  the LLM grounded and reduces hallucination).

Keeping results structured + summarized is the single most important habit in
this codebase: raw command output fed straight to an LLM causes missed signals
and confabulated conclusions. We parse first, then narrate.
"""

from __future__ import annotations

import abc
import time
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Severity(StrEnum):
    """Traffic-light verdict for a single tool run, used by the UI."""

    OK = "ok"        # checks passed / target healthy
    WARN = "warn"    # degraded (loss, high latency, expiring cert, ...)
    FAIL = "fail"    # the thing we probed is broken / unreachable
    INFO = "info"    # neutral observation (resolved DNS, open ports list)


class ToolResult(BaseModel):
    """Structured outcome of one tool invocation."""

    tool: str
    ok: bool = True                       # did the tool itself execute without error?
    severity: Severity = Severity.INFO
    data: dict[str, Any] = Field(default_factory=dict)
    summary_zh: str = ""                  # plain-Chinese interpretation of `data`
    error: str | None = None              # populated when ok=False
    duration_ms: float = 0.0

    def as_llm_content(self) -> str:
        """Compact, LLM-friendly rendering fed back into the function-call loop."""
        if not self.ok:
            return f"[工具执行失败] {self.tool}: {self.error}"
        # summary first (the LLM reads this), then the raw numbers for precision.
        import json

        return f"{self.summary_zh}\n[结构化数据] {json.dumps(self.data, ensure_ascii=False)}"


class Tool(abc.ABC):
    """Base class for all diagnostic tools."""

    #: short id used by the LLM and the registry
    name: str = ""
    #: one-line description shown to the LLM in the tools list
    description: str = ""
    #: JSON-schema for the arguments (OpenAI function-calling "parameters")
    parameters: dict[str, Any] = {}

    @abc.abstractmethod
    async def run(self, **kwargs: Any) -> ToolResult:
        """Execute the diagnostic and return a structured result."""

    # -- helpers ------------------------------------------------------------
    def openai_schema(self) -> dict[str, Any]:
        """Render this tool in the OpenAI/GLM ``tools`` format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters or {"type": "object", "properties": {}},
            },
        }

    @staticmethod
    def _timed() -> _Timer:
        return _Timer()


class _Timer:
    """Tiny context manager that measures elapsed milliseconds."""

    def __init__(self) -> None:
        self.start = 0.0

    def __enter__(self) -> _Timer:
        self.start = time.perf_counter()
        return self

    def __exit__(self, *exc: object) -> None:
        self.ms = (time.perf_counter() - self.start) * 1000.0
