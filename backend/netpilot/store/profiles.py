"""Profile store — saved diagnostic targets (à la NETworkManager's hosts).

A *profile* is just a named target the operator runs diagnosis against often:
``{name: "生产-OA", target: "oa.internal:443", kind: "host", notes: "..."}``.
Stored as one JSON file; small, atomic-ish writes, no server process required.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class Profile(BaseModel):
    id: str
    name: str
    target: str                       # host, host:port, or full URL
    kind: str = "host"                # "host" | "url"
    notes: str = ""
    tags: list[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


class ProfileStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.touch(exist_ok=True)

    # -- io -----------------------------------------------------------------
    def _read_all(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8") or "[]")
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            pass
        return []

    def _write_all(self, items: list[dict[str, Any]]) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    # -- public API ---------------------------------------------------------
    def list(self) -> list[Profile]:
        with self._lock:
            return [Profile(**p) for p in self._read_all()]

    def get(self, profile_id: str) -> Profile | None:
        with self._lock:
            for p in self._read_all():
                if p.get("id") == profile_id:
                    return Profile(**p)
        return None

    def create(self, payload: dict[str, Any]) -> Profile:
        now = datetime.now(timezone.utc).isoformat()
        profile = Profile(
            id=uuid.uuid4().hex[:12],
            name=str(payload.get("name", "")).strip() or "未命名",
            target=str(payload.get("target", "")).strip(),
            kind=str(payload.get("kind", "host")),
            notes=str(payload.get("notes", "")),
            tags=list(payload.get("tags", []) or []),
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            items = self._read_all()
            items.append(profile.model_dump())
            self._write_all(items)
        return profile

    def update(self, profile_id: str, payload: dict[str, Any]) -> Profile | None:
        with self._lock:
            items = self._read_all()
            for p in items:
                if p.get("id") == profile_id:
                    for k in ("name", "target", "kind", "notes", "tags"):
                        if k in payload:
                            p[k] = payload[k]
                    p["updated_at"] = datetime.now(timezone.utc).isoformat()
                    self._write_all(items)
                    return Profile(**p)
        return None

    def delete(self, profile_id: str) -> bool:
        with self._lock:
            items = self._read_all()
            new = [p for p in items if p.get("id") != profile_id]
            if len(new) == len(items):
                return False
            self._write_all(new)
            return True
