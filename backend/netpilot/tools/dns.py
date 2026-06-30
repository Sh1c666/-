"""DNS resolution tool."""

from __future__ import annotations

import asyncio
from typing import Any

import dns.exception
import dns.resolver

from .base import Severity, Tool, ToolResult, _Timer


class DnsLookupTool(Tool):
    name = "dns_lookup"
    description = (
        "解析域名的 DNS 记录(A/AAAA/CNAME),判断解析是否成功、解析到的 IP 是否合理。"
        "排查的第一步:解析失败或解析到错误/陈旧 IP 都会直接导致'连不上'。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "host": {"type": "string", "description": "要解析的域名,例如 baidu.com"},
            "rdtype": {
                "type": "string",
                "enum": ["A", "AAAA", "CNAME", "MX", "ANY"],
                "description": "默认解析 A(IPv4)。可选 AAAA/CNAME/MX。",
                "default": "A",
            },
            "timeout": {"type": "number", "description": "单次查询超时(秒),默认 4", "default": 4},
        },
        "required": ["host"],
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        host = str(kwargs.get("host", "")).strip()
        rdtype = str(kwargs.get("rdtype", "A")).upper()
        timeout = float(kwargs.get("timeout", 4))
        if not host:
            return ToolResult(tool=self.name, ok=False, error="缺少参数 host")

        with _Timer() as t:
            res = await asyncio.to_thread(self._resolve, host, rdtype, timeout)
        res.duration_ms = t.ms  # type: ignore[attr-defined]
        return res

    # -- sync resolver (run in a worker thread) -----------------------------
    def _resolve(self, host: str, rdtype: str, timeout: float) -> ToolResult:
        resolver = dns.resolver.Resolver(configure=True)
        resolver.lifetime = timeout
        resolver.timeout = timeout

        records: list[dict[str, str]] = []
        try:
            answer = resolver.resolve(host, rdtype, raise_on_no_answer=False)
        except dns.resolver.NXDOMAIN:
            return ToolResult(
                tool=self.name,
                severity=Severity.FAIL,
                summary_zh=f"DNS 解析失败:域名 {host} 不存在(NXDOMAIN),"
                "可能是域名拼错、域名未注册或已注销。",
                data={"host": host, "rdtype": rdtype, "status": "NXDOMAIN"},
            )
        except dns.resolver.NoAnswer:
            return ToolResult(
                tool=self.name,
                severity=Severity.WARN,
                summary_zh=f"{host} 没有 {rdtype} 记录,但域名本身存在。",
                data={"host": host, "rdtype": rdtype, "status": "NO_ANSWER"},
            )
        except (dns.resolver.NoNameservers, dns.exception.Timeout) as exc:
            return ToolResult(
                tool=self.name,
                severity=Severity.FAIL,
                summary_zh=f"DNS 查询失败:{type(exc).__name__}。本机 DNS 服务器不可达或无响应,"
                "检查本机 DNS 配置与上游 DNS 可用性。",
                data={"host": host, "rdtype": rdtype, "status": type(exc).__name__},
            )
        except dns.exception.DNSException as exc:
            return ToolResult(
                tool=self.name,
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
                summary_zh=f"DNS 解析出现异常:{type(exc).__name__}。",
                data={"host": host, "rdtype": rdtype, "status": type(exc).__name__},
            )

        rrdata = getattr(answer, "rrset", None)
        ttl = int(getattr(rrdata, "ttl", 0)) if rrdata else 0
        for rdata in answer:
            records.append({"value": rdata.to_text(), "type": rdtype})

        ips = [r["value"] for r in records if r["type"] in ("A", "AAAA")]
        status = "OK"
        severity = Severity.OK if ips else Severity.INFO
        if ips:
            ip_list = "、".join(ips)
            summary = (
                f"{host} 解析成功,共 {len(ips)} 条 {rdtype} 记录:{ip_list}(TTL {ttl}s)。"
            )
        else:
            summary = f"{host} 解析到 {len(records)} 条 {rdtype} 记录:{records}。"

        return ToolResult(
            tool=self.name,
            severity=severity,
            summary_zh=summary,
            data={
                "host": host,
                "rdtype": rdtype,
                "status": status,
                "ttl": ttl,
                "records": records,
                "resolved_ips": ips,
            },
        )
