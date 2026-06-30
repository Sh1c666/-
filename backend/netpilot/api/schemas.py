"""Request/response schemas for the REST + SSE API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DiagnoseRequest(BaseModel):
    symptom: str = Field(..., description="故障现象,自然语言描述")
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="可选补充上下文,如 {target, recently_changed, expected_ip}",
    )


class ProfileCreate(BaseModel):
    name: str
    target: str
    kind: str = "host"
    notes: str = ""
    tags: list[str] = Field(default_factory=list)


class ProfileUpdate(BaseModel):
    name: str | None = None
    target: str | None = None
    kind: str | None = None
    notes: str | None = None
    tags: list[str] | None = None


class SettingsUpdate(BaseModel):
    llm: dict[str, Any] | None = None
    privacy: dict[str, Any] | None = None


class ToolRunRequest(BaseModel):
    name: str = Field(..., description="工具名,如 ping/tcp_ping/port_scan")
    arguments: dict[str, Any] = Field(default_factory=dict, description="工具参数")
