"""Port scan tool — pure-Python concurrent TCP connect scan.

No nmap dependency, no privileges. A connect() scan classifies each port as:

* ``open``    — SYN/SYN-ACK completed (something is listening)
* ``closed``  — RST received (host is up, nothing listens)
* ``filtered`` — timeout / no response (likely firewalled)

The distinction between *closed* and *filtered* is the useful signal: a host
where every interesting port is *filtered* points at a firewall, whereas
*closed* ports mean the host is reachable but the service isn't running.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from .base import Severity, Tool, ToolResult, _Timer

COMMON_PORTS = {
    "web": [80, 443, 8080, 8443],
    "remote": [22, 23, 3389, 5900],
    "db": [3306, 5432, 1433, 1521, 6379, 27017, 9200],
    "mail": [25, 110, 143, 465, 587, 993, 995],
    "common": [
        20, 21, 22, 23, 25, 53, 80, 110, 143, 443, 465, 587, 993, 995,
        1433, 1521, 3306, 3389, 5432, 5900, 6379, 8080, 8443, 9200, 27017,
    ],
}


async def _probe(host: str, port: int, timeout: float) -> str:
    try:
        fut = asyncio.open_connection(host, port)
        reader, writer = await asyncio.wait_for(fut, timeout=timeout)
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
        return "open"
    except ConnectionRefusedError:
        return "closed"
    except (TimeoutError, asyncio.TimeoutError):
        return "filtered"
    except OSError as e:
        # host unreachable etc.
        if "unroutable" in str(e).lower() or "unreachable" in str(e).lower():
            return "unreachable"
        return "filtered"


class PortScanTool(Tool):
    name = "port_scan"
    description = (
        "扫描目标主机的 TCP 端口,区分 open/closed/filtered。"
        "用于判断服务是否在监听、是否有防火墙拦截。支持预置端口集(web/remote/db/mail/common)或自定义端口列表。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "host": {"type": "string", "description": "目标主机(IP 或域名)"},
            "ports": {
                "type": "string",
                "description": "端口集名(web/remote/db/mail/common),或自定义列表如 '80,443,8080',或范围 '8000-8100'",
                "default": "common",
            },
            "timeout": {"type": "number", "description": "单端口超时秒数,默认 1.5", "default": 1.5},
            "concurrency": {"type": "integer", "description": "并发数,默认 50", "default": 50},
        },
        "required": ["host"],
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        host = str(kwargs.get("host", "")).strip()
        ports_arg = str(kwargs.get("ports", "common"))
        timeout = float(kwargs.get("timeout", 1.5))
        concurrency = int(kwargs.get("concurrency", 50))
        if not host:
            return ToolResult(tool=self.name, ok=False, error="缺少参数 host")

        ports = self._parse_ports(ports_arg)
        if not ports:
            return ToolResult(tool=self.name, ok=False, error=f"无法解析端口参数: {ports_arg}")

        sem = asyncio.Semaphore(max(1, concurrency))

        async def guarded(p: int) -> tuple[int, str]:
            async with sem:
                return p, await _probe(host, p, timeout)

        with _Timer() as t:
            results = await asyncio.gather(*(guarded(p) for p in ports))

        open_ports = sorted(p for p, st in results if st == "open")
        closed = sorted(p for p, st in results if st == "closed")
        filtered = sorted(p for p, st in results if st == "filtered")
        unreachable = any(st == "unreachable" for _, st in results)

        severity, summary = self._judge(host, open_ports, closed, filtered, unreachable)
        return ToolResult(
            tool=self.name,
            severity=severity,
            summary_zh=summary,
            data={
                "host": host,
                "scanned_count": len(ports),
                "open": open_ports,
                "closed": closed,
                "filtered": filtered,
                "unreachable": unreachable,
            },
            duration_ms=t.ms,
        )

    def _parse_ports(self, arg: str) -> list[int]:
        arg = arg.strip().lower()
        if arg in COMMON_PORTS:
            return list(COMMON_PORTS[arg])
        out: list[int] = []
        seen: set[int] = set()
        for part in arg.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                lo, _, hi = part.partition("-")
                try:
                    for p in range(int(lo), int(hi) + 1):
                        if 0 < p < 65536 and p not in seen:
                            out.append(p)
                            seen.add(p)
                except ValueError:
                    continue
            else:
                try:
                    p = int(part)
                    if 0 < p < 65536 and p not in seen:
                        out.append(p)
                        seen.add(p)
                except ValueError:
                    continue
        return out

    def _judge(
        self,
        host: str,
        open_ports: list[int],
        closed: list[int],
        filtered: list[int],
        unreachable: bool,
    ) -> tuple[Severity, str]:
        if unreachable:
            return Severity.FAIL, f"{host} 主机不可达,所有端口探测均返回 unreachable。"
        if open_ports:
            return Severity.OK, (
                f"{host} 扫描完成,开放端口: {open_ports}。"
                f"closed {len(closed)} 个, filtered {len(filtered)} 个。目标在线且有服务在监听。"
            )
        if filtered and not closed:
            return Severity.WARN, (
                f"{host} 所有探测端口均为 filtered(超时无响应)——"
                "强烈提示有防火墙/安全组在丢包,或主机禁用了 RST。建议核对防火墙规则。"
            )
        if closed and not filtered:
            return Severity.WARN, (
                f"{host} 可达(RST),但所扫端口均 closed——没有服务在监听。"
                "属于应用/服务未启动,而非网络链路问题。"
            )
        return Severity.WARN, (
            f"{host} 无开放端口(closed {len(closed)}, filtered {len(filtered)})。"
            "结合端口与服务对应关系判断:目标端口在列表中但未开放 → 服务未起/被拦。"
        )
