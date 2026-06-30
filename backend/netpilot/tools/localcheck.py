"""Local-machine self-check tool.

Before chasing the network, check the *local* machine: a surprising fraction of
"the network is down" tickets are a misconfigured proxy, a stale ``hosts``
override, or a wonky local resolver. This tool surfaces those in one shot so the
agent doesn't waste hops blaming an innocent remote host.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path
from typing import Any

import dns.resolver

from .base import Severity, Tool, ToolResult, _Timer

_WIN = sys.platform.startswith("win")


def _hosts_path() -> Path:
    if _WIN:
        return Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "drivers" / "etc" / "hosts"
    return Path("/etc/hosts")


def _read_hosts_entries(target: str) -> list[dict[str, str]]:
    path = _hosts_path()
    if not path.exists():
        return []
    entries: list[dict[str, str]] = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2 and target.lower() in [p.lower() for p in parts[1:]]:
                entries.append({"ip": parts[0], "host": target})
    except OSError:
        pass
    return entries


def _detect_proxy() -> dict[str, str | None]:
    return {
        "http_proxy": os.environ.get("http_proxy") or os.environ.get("HTTP_PROXY"),
        "https_proxy": os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY"),
        "no_proxy": os.environ.get("no_proxy") or os.environ.get("NO_PROXY"),
    }


def _detect_dns_servers() -> list[str]:
    # Try the resolver's configured nameservers (works cross-platform via dnspython).
    try:
        return [str(ns) for ns in dns.resolver.Resolver(configure=True).nameservers]
    except Exception:  # noqa: BLE001
        return []


async def _windows_dns() -> list[str]:
    """Best-effort DNS server list from `ipconfig /all`."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ipconfig", "/all",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=8)
        text = out.decode(errors="replace")
        return list(dict.fromkeys(re.findall(r"DNS Servers?\.?\s*:?\s*(\d{1,3}(?:\.\d{1,3}){3})", text)))
    except Exception:  # noqa: BLE001
        return []


class LocalCheckTool(Tool):
    name = "local_check"
    description = (
        "检查本机与排查相关的配置:HTTP/HTTPS 代理环境变量、hosts 文件中是否存在目标域名的静态映射、"
        "本机使用的 DNS 服务器。这些本机配置常常被误当成'网络故障',应优先排除。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "host": {
                "type": "string",
                "description": "正在排查的目标域名/主机名,用于在 hosts 中查找匹配项",
            },
        },
        "required": ["host"],
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        host = str(kwargs.get("host", "")).strip()
        if not host:
            return ToolResult(tool=self.name, ok=False, error="缺少参数 host")

        with _Timer() as t:
            proxy = _detect_proxy()
            hosts_entries = _read_hosts_entries(host)
            if _WIN:
                dns_servers = await _windows_dns() or _detect_dns_servers()
            else:
                dns_servers = _detect_dns_servers()

        severity, summary = self._judge(host, proxy, hosts_entries, dns_servers)
        return ToolResult(
            tool=self.name,
            severity=severity,
            summary_zh=summary,
            data={
                "host": host,
                "proxy": proxy,
                "hosts_entries": hosts_entries,
                "dns_servers": dns_servers,
                "hosts_override_present": bool(hosts_entries),
                "proxy_active": bool(proxy["http_proxy"] or proxy["https_proxy"]),
            },
            duration_ms=t.ms,
        )

    def _judge(
        self,
        host: str,
        proxy: dict[str, str | None],
        hosts_entries: list[dict[str, str]],
        dns_servers: list[str],
    ) -> tuple[Severity, str]:
        flags: list[str] = []
        if proxy.get("http_proxy") or proxy.get("https_proxy"):
            flags.append(
                f"本机配置了代理(http={proxy['http_proxy']}, https={proxy['https_proxy']})——"
                "若目标不在 no_proxy 内,所有流量将走代理,代理故障会伪装成'连不上'。"
            )
        if hosts_entries:
            flags.append(
                f"hosts 文件存在 {host} 的静态映射 → {hosts_entries},"
                "会绕过 DNS。若映射到错误/陈旧 IP,将直接导致连不上,务必核对。"
            )
        if not dns_servers:
            flags.append("未能检测到本机 DNS 服务器,本机 DNS 配置可能异常。")
        elif any(ip.startswith(("127.", "0.")) and ip != "127.0.0.11" for ip in dns_servers):
            pass  # local resolver is fine
        if not flags:
            return Severity.OK, (
                f"本机自检通过:无代理(或代理不影响 {host}),hosts 无 {host} 的静态映射,"
                f"DNS 服务器={dns_servers}。本机配置不是故障原因。"
            )
        return Severity.WARN, "本机自检发现可疑配置:" + " ".join(flags)
