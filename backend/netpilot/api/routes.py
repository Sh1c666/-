"""API routes: health, tools, settings, profiles, and the SSE diagnose stream."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from .. import __version__ as VERSION
from .. import tools as toolreg
from ..agent.orchestrator import run_diagnosis
from ..config import runtime, startup_settings
from ..store import ProfileStore
from .schemas import DiagnoseRequest, ProfileCreate, ProfileUpdate, SettingsUpdate, ToolRunRequest

router = APIRouter(prefix="/api")

profile_store = ProfileStore(startup_settings.data_path / "profiles.json")


# --------------------------------------------------------------------------- health
@router.get("/health")
def health() -> dict[str, Any]:
    cfg = runtime.snapshot()
    return {
        "status": "ok",
        "version": VERSION,
        "has_api_key": bool(cfg.llm.api_key),
        "model": cfg.llm.model,
        "mask_internal_ips": cfg.privacy.mask_internal_ips,
    }


# --------------------------------------------------------------------------- tools
@router.get("/tools")
def list_tools() -> dict[str, Any]:
    """Tool catalog with JSON-schema `parameters`, so the UI can render a form
    for manual (no-LLM) execution."""
    return {
        "tools": [
            {"name": t.name, "description": t.description, "parameters": t.parameters}
            for t in toolreg.all_tools().values()
        ]
    }


@router.post("/tools/run")
async def run_tool(req: ToolRunRequest) -> dict[str, Any]:
    """Run a single diagnostic tool directly (no Agent), returning its
    structured result. This is the 'manual network toolkit' mode."""
    result = await toolreg.dispatch(req.name, req.arguments)
    return {
        "tool": result.tool,
        "severity": result.severity.value,
        "ok": result.ok,
        "summary_zh": result.summary_zh,
        "data": result.data,
        "duration_ms": round(result.duration_ms, 1),
        "error": result.error,
    }


# --------------------------------------------------------------------------- settings
def _public_settings() -> dict[str, Any]:
    cfg = runtime.snapshot()
    key = cfg.llm.api_key
    preview = ("•" * max(0, len(key) - 4) + key[-4:]) if key else ""
    return {
        "llm": {
            "base_url": cfg.llm.base_url,
            "model": cfg.llm.model,
            "protocol": cfg.llm.protocol,
            "temperature": cfg.llm.temperature,
            "max_tokens": cfg.llm.max_tokens,
            "max_steps": cfg.llm.max_steps,
            "has_api_key": bool(key),
            "api_key_preview": preview,
        },
        "privacy": {"mask_internal_ips": cfg.privacy.mask_internal_ips},
    }


@router.get("/settings")
def get_settings() -> dict[str, Any]:
    return _public_settings()


@router.put("/settings")
def update_settings(payload: SettingsUpdate) -> dict[str, Any]:
    runtime.update(payload.model_dump(exclude_none=True))
    return _public_settings()


# --------------------------------------------------------------------------- profiles
@router.get("/profiles")
def list_profiles() -> dict[str, Any]:
    return {"profiles": [p.model_dump() for p in profile_store.list()]}


@router.post("/profiles")
def create_profile(payload: ProfileCreate) -> dict[str, Any]:
    return profile_store.create(payload.model_dump()).model_dump()


@router.put("/profiles/{profile_id}")
def update_profile(profile_id: str, payload: ProfileUpdate) -> dict[str, Any]:
    updated = profile_store.update(profile_id, payload.model_dump(exclude_none=True))
    if updated is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return updated.model_dump()


@router.delete("/profiles/{profile_id}")
def delete_profile(profile_id: str) -> dict[str, Any]:
    if not profile_store.delete(profile_id):
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"deleted": profile_id}


# --------------------------------------------------------------------------- diagnose (SSE)
async def _diagnose_stream(req: DiagnoseRequest) -> AsyncIterator[str]:
    """Wrap agent events as SSE ``data:`` lines (one JSON object per line)."""
    async for event in run_diagnosis(req.symptom, req.context):
        yield json.dumps(event, ensure_ascii=False)


@router.post("/diagnose")
def diagnose(req: DiagnoseRequest) -> EventSourceResponse:
    """Start a diagnosis. Returns an SSE stream of agent events."""
    return EventSourceResponse(_diagnose_stream(req))
