"""Privacy / desensitization layer.

Enterprise network topology (internal IPs, hostnames) is sensitive. Before any
diagnostic context leaves the process for a cloud LLM, :class:`PrivacyMask`
replaces private/internal IPv4 addresses with stable, opaque tokens such as
``[内网IP-1]``. The mapping is kept locally so results streamed back to the user
can be restored to their real values.

Scope:
* Only RFC1918 / loopback / link-local / reserved IPv4 addresses are masked.
* Public IPs are left intact — the agent needs them to reason about which ISP
  hop is breaking. (A stricter "mask everything" mode can be added later.)
* IPv6 literals and domain names are not masked by default.

Usage is per-agent-run: create one ``PrivacyMask``, mask everything going to
the LLM, and ``unmask`` everything coming back for display.
"""

from __future__ import annotations

import ipaddress
import re
from itertools import count

_IPV4_RE = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")
_TOKEN_RE = re.compile(r"\[内网IP-(\d+)\]")


def _is_sensitive(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return bool(addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved)


class PrivacyMask:
    """Bidirectional mapper between real internal IPs and opaque tokens."""

    def __init__(self) -> None:
        self._counter = count(start=1)
        self._to_token: dict[str, str] = {}
        self._to_real: dict[str, str] = {}

    def mask_ip(self, ip: str) -> str:
        if not _is_sensitive(ip):
            return ip
        token = self._to_token.get(ip)
        if token is None:
            token = f"[内网IP-{next(self._counter)}]"
            self._to_token[ip] = token
            self._to_real[token] = ip
        return token

    def unmask_ip(self, token_or_ip: str) -> str:
        return self._to_real.get(token_or_ip, token_or_ip)

    def mask(self, text: str) -> str:
        """Replace every sensitive IPv4 in ``text`` with its token."""
        if not text:
            return text
        return _IPV4_RE.sub(lambda m: self.mask_ip(m.group(0)), text)

    def unmask(self, text: str) -> str:
        """Restore real IPs into ``text`` (used when rendering to the user)."""
        if not text:
            return text
        return _TOKEN_RE.sub(lambda m: self._to_real.get(f"[内网IP-{m.group(1)}]", m.group(0)), text)

    @property
    def mapping(self) -> dict[str, str]:
        """token -> real IP, for debugging / the UI's privacy inspector."""
        return dict(self._to_real)
