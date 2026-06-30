"""Event types streamed from the agent to the UI over SSE.

Each event is a small JSON object with a ``type`` discriminator. The frontend
dispatches on ``type`` and renders the rest. Keeping these as plain string
constants (rather than pydantic models) makes the SSE wire format trivial and
the TS mirror in ``frontend/src/types.ts`` easy to keep in sync.
"""

from __future__ import annotations

# A run begins. Carries the original symptom and whether masking is active.
META = "meta"

# Free-form assistant reasoning, shown between tool calls (the "thinking").
MESSAGE = "message"

# The agent decided to invoke a diagnostic tool.
TOOL_CALL = "tool_call"

# A tool finished; carries the structured verdict + summary.
TOOL_RESULT = "tool_result"

# The run concluded with a diagnosis. Fields:
#   is_network_issue: bool | null
#   layer: str (which OSI/operation layer the fault sits at, or "非网络问题")
#   root_cause: str
#   evidence: list[str]   (each cites a tool + metric)
#   recommendation: str
#   confidence: "high" | "medium" | "low" | null
#   text: str  (full natural-language report, fallback when unstructured)
FINAL = "final"

# Something went wrong; the run aborts.
ERROR = "error"

# Run finished (always emitted last). Carries step count + total duration.
DONE = "done"

__all__ = ["META", "MESSAGE", "TOOL_CALL", "TOOL_RESULT", "FINAL", "ERROR", "DONE"]
