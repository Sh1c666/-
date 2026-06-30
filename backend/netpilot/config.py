"""Application configuration.

Two layers:

* ``Settings`` — immutable values loaded at startup from environment / ``.env``.
  These are the *defaults*.
* ``runtime`` — a singleton :class:`RuntimeConfig` that begins as a copy of
  ``Settings`` but can be **updated at runtime from the UI** and persisted to
  ``data/settings.json``. Everything that runs on a per-request basis
  (the LLM client, the agent, the privacy layer) reads from ``runtime`` so a
  user can change the API key, model, or privacy mode without restarting the
  server.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve paths ---------------------------------------------------------------
BACKEND_DIR = Path(__file__).resolve().parent.parent          # .../backend
PROJECT_DIR = BACKEND_DIR.parent                              # .../AI_NetworkManage
FRONTEND_DIST = BACKEND_DIR.parent / "frontend" / "dist"      # built SPA, served by FastAPI
DEFAULT_DATA_DIR = BACKEND_DIR / "data"


class Settings(BaseSettings):
    """Immutable startup settings, sourced from env / .env."""

    model_config = SettingsConfigDict(
        env_prefix="NETPILOT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM — any OpenAI-compatible endpoint (DeepSeek / GLM / OpenAI / Ollama …).
    # Defaults match DeepSeek; override base_url + model in .env or the UI.
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"
    # "openai" (OpenAI-compatible /chat/completions) or "anthropic" (Anthropic
    # Messages API, e.g. BigModel's /api/anthropic). The latter is needed when a
    # provider's subscription only covers its Claude-compatible endpoint.
    llm_protocol: str = "openai"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 2048

    # Agent
    agent_max_steps: int = 12

    # Privacy
    privacy_mask_internal_ips: bool = True

    # Server
    host: str = "127.0.0.1"
    port: int = 8000
    allow_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Data
    data_dir: str = str(DEFAULT_DATA_DIR)

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allow_origins.split(",") if o.strip()]

    @property
    def data_path(self) -> Path:
        p = Path(self.data_dir)
        if not p.is_absolute():
            p = BACKEND_DIR / p
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def settings_file(self) -> Path:
        return self.data_path / "settings.json"


class LLMConfig(BaseModel):
    """Mutable LLM connection settings exposed to the UI."""

    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"
    protocol: str = "openai"  # "openai" | "anthropic" — picks the transport in llm_client
    temperature: float = 0.2
    max_tokens: int = 2048
    max_steps: int = 12


class PrivacyConfig(BaseModel):
    mask_internal_ips: bool = True


class RuntimeConfig(BaseModel):
    """The live, writable configuration used by every request."""

    llm: LLMConfig = Field(default_factory=LLMConfig)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)


class Runtime:
    """Thread-safe holder for the live config, persisted to disk."""

    def __init__(self, startup: Settings) -> None:
        self._lock = threading.RLock()
        self._startup = startup
        self.cfg = RuntimeConfig(
            llm=LLMConfig(
                api_key=startup.llm_api_key,
                base_url=startup.llm_base_url,
                model=startup.llm_model,
                protocol=startup.llm_protocol,
                temperature=startup.llm_temperature,
                max_tokens=startup.llm_max_tokens,
                max_steps=startup.agent_max_steps,
            ),
            privacy=PrivacyConfig(mask_internal_ips=startup.privacy_mask_internal_ips),
        )
        self._load_from_disk()

    # -- persistence --------------------------------------------------------
    def _load_from_disk(self) -> None:
        path = self._startup.settings_file
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            # Only adopt keys we know about; never trust unknown fields blindly.
            llm = data.get("llm") or {}
            priv = data.get("privacy") or {}
            self.cfg.llm = LLMConfig(**{k: v for k, v in llm.items() if k in LLMConfig.model_fields})
            self.cfg.privacy = PrivacyConfig(
                **{k: v for k, v in priv.items() if k in PrivacyConfig.model_fields}
            )
        except (json.JSONDecodeError, TypeError, ValueError):
            # Corrupt settings file — fall back to startup defaults silently.
            pass

    def _persist(self) -> None:
        path = self._startup.settings_file
        with contextlib.suppress(OSError):  # persistence is best-effort; never crash a request
            path.write_text(
                json.dumps(self.cfg.model_dump(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

    # -- public API ---------------------------------------------------------
    def snapshot(self) -> RuntimeConfig:
        """Return a cheap copy-safe view (callers read fields, not mutate)."""
        with self._lock:
            return self.cfg.model_copy(deep=True)

    def update(self, payload: dict[str, Any]) -> RuntimeConfig:
        with self._lock:
            if "llm" in payload and isinstance(payload["llm"], dict):
                # An empty api_key in the payload means "leave unchanged".
                incoming = payload["llm"]
                if not incoming.get("api_key"):
                    incoming = {**incoming, "api_key": self.cfg.llm.api_key}
                self.cfg.llm = LLMConfig(
                    **{k: v for k, v in incoming.items() if k in LLMConfig.model_fields}
                )
            if "privacy" in payload and isinstance(payload["privacy"], dict):
                self.cfg.privacy = PrivacyConfig(
                    **{
                        k: v
                        for k, v in payload["privacy"].items()
                        if k in PrivacyConfig.model_fields
                    }
                )
            self._persist()
            return self.cfg.model_copy(deep=True)


# Module-level singletons -----------------------------------------------------
startup_settings = Settings()
runtime = Runtime(startup_settings)


# Keep os.environ honest if the key was only in .env (some libs read env directly).
if startup_settings.llm_api_key and not os.environ.get("NETPILOT_LLM_API_KEY"):
    os.environ["NETPILOT_LLM_API_KEY"] = startup_settings.llm_api_key
