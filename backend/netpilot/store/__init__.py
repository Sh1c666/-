"""On-disk stores (profiles, sessions). JSON files under ``data/`` — no DB
dependency, which keeps the app trivially portable for a single-user tool."""

from .profiles import ProfileStore

__all__ = ["ProfileStore"]
