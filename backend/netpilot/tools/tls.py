"""TLS inspection tool — certificate validity, chain, hostname, version.

Connects twice:
1. With default verification — captures the exact trust failure (expired,
   wrong-host, self-signed, incomplete chain) so we can name the problem.
2. With verification disabled — so we can still parse and report the cert
   details even when trust fails (e.g. to show *when* an expired cert expires).
"""

from __future__ import annotations

import asyncio
import socket
import ssl
from datetime import datetime, timezone
from typing import Any

from cryptography import x509
from cryptography.hazmat.backends import default_backend

from .base import Severity, Tool, ToolResult, _Timer


def _cn(name_attrs: Any) -> str:
    """Pull the CN out of an x509 Name (empty string if absent)."""
    try:
        attrs = name_attrs.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
        return attrs[0].value if attrs else ""
    except Exception:  # noqa: BLE001
        return ""


def _connect(host: str, port: int, verify: bool, timeout: float) -> dict[str, Any]:
    ctx = ssl.create_default_context()
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    with (
        socket.create_connection((host, port), timeout=timeout) as raw,
        ctx.wrap_socket(raw, server_hostname=host) as s,
    ):
        der = s.getpeercert(binary_form=True)
        version = s.version()
        cipher = s.cipher()
    cert = x509.load_der_x509_certificate(der, default_backend()) if der else None
    return {"cert": cert, "tls_version": version, "cipher": cipher[0] if cipher else None}


class TlsInspectTool(Tool):
    name = "tls_inspect"
    description = (
        "检查 HTTPS 服务的 TLS 证书与握手:签发者、有效期(剩余天数)、证书链、域名是否匹配、TLS 版本。"
        "用于排查 HTTPS 报错(证书过期/链不全/域名不符/版本不兼容)。仅适用于 443 等 TLS 端口。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "host": {"type": "string", "description": "目标主机(域名;若是 IP 则证书域名匹配会失败)"},
            "port": {"type": "integer", "description": "TLS 端口,默认 443", "default": 443},
            "timeout": {"type": "number", "description": "握手超时秒数,默认 5", "default": 5},
        },
        "required": ["host"],
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        host = str(kwargs.get("host", "")).strip()
        port = int(kwargs.get("port", 443))
        timeout = float(kwargs.get("timeout", 5))
        if not host:
            return ToolResult(tool=self.name, ok=False, error="缺少参数 host")

        with _Timer() as t:
            # 1) verified connect — what (if anything) is wrong?
            verify_error: str | None = None
            try:
                await asyncio.to_thread(_connect, host, port, True, timeout)
            except ssl.SSLCertVerificationError as e:
                verify_error = e.verify_message or str(e)
            except ssl.SSLError as e:
                return ToolResult(
                    tool=self.name,
                    severity=Severity.FAIL,
                    summary_zh=f"TLS 握手失败({e.reason or e}):无法建立加密连接,可能是协议/加密套件不兼容或端口非 TLS。",
                    data={"host": host, "port": port, "status": "SSL_ERROR", "error": str(e)},
                    duration_ms=t.ms,
                )
            except (OSError, ConnectionError) as e:
                return ToolResult(
                    tool=self.name,
                    severity=Severity.FAIL,
                    summary_zh=f"无法连接 {host}:{port} 进行 TLS 检查:{e}。确认端口可达后再试。",
                    data={"host": host, "port": port, "status": "UNREACHABLE", "error": str(e)},
                    duration_ms=t.ms,
                )

            # 2) unverified connect — read the cert details regardless of trust.
            try:
                info = await asyncio.to_thread(_connect, host, port, False, timeout)
            except Exception as e:  # noqa: BLE001
                return ToolResult(
                    tool=self.name,
                    ok=False,
                    error=str(e),
                    summary_zh=f"读取 {host} 证书失败:{e}。",
                    data={"host": host, "port": port, "verify_error": verify_error},
                    duration_ms=t.ms,
                )

        cert = info["cert"]
        if cert is None:
            return ToolResult(
                tool=self.name,
                ok=False,
                error="未获取到证书",
                summary_zh=f"{host}:{port} 未返回证书。",
                data={"host": host, "port": port, "verify_error": verify_error},
                duration_ms=t.ms,
            )

        now = datetime.now(timezone.utc)
        not_before = cert.not_valid_before_utc
        not_after = cert.not_valid_after_utc
        days_left = (not_after - now).days
        subject_cn = _cn(cert.subject)
        issuer_cn = _cn(cert.issuer)
        try:
            san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            san_list = san.get_values_for_type(x509.DNSName)
        except x509.ExtensionNotFound:
            san_list = []

        severity, summary = self._judge(
            host,
            subject_cn,
            issuer_cn,
            not_before,
            not_after,
            days_left,
            san_list,
            verify_error,
            info.get("tls_version"),
            info.get("cipher"),
        )
        return ToolResult(
            tool=self.name,
            severity=severity,
            summary_zh=summary,
            data={
                "host": host,
                "port": port,
                "status": "OK" if verify_error is None else "VERIFY_FAILED",
                "subject_cn": subject_cn,
                "san": san_list,
                "issuer_cn": issuer_cn,
                "valid_from": not_before.isoformat(),
                "valid_to": not_after.isoformat(),
                "days_left": days_left,
                "verify_error": verify_error,
                "hostname_matches": (
                    host == subject_cn
                    or host in san_list
                    or self._wildcard_match(host, subject_cn, san_list)
                ),
                "tls_version": info.get("tls_version"),
                "cipher": info.get("cipher"),
            },
            duration_ms=t.ms,
        )

    @staticmethod
    def _wildcard_match(host: str, cn: str, sans: list[str]) -> bool:
        names = [cn] + list(sans)
        for name in names:
            if name.startswith("*."):
                suffix = name[1:]
                if host.endswith(suffix) and "." in host[: -len(suffix)]:
                    return True
        return False

    def _judge(
        self,
        host: str,
        subject_cn: str,
        issuer_cn: str,
        not_before: datetime,
        not_after: datetime,
        days_left: int,
        san_list: list[str],
        verify_error: str | None,
        tls_version: str | None,
        cipher: str | None,
    ) -> tuple[Severity, str]:
        base = (
            f"证书 CN={subject_cn or '(无)'}, 签发者={issuer_cn or '(无)'}, "
            f"有效期 {not_before.date()} ~ {not_after.date()}(剩余 {days_left} 天), "
            f"TLS {tls_version or '?'}/{cipher or '?'}, SAN={san_list[:5]}."
        )
        if days_left < 0:
            return Severity.FAIL, f"{host} 证书已过期 {abs(days_left)} 天!这是 HTTPS 报错的直接原因,需立即续签。"
        if verify_error and "expired" in verify_error.lower():
            return Severity.FAIL, f"{host} 证书已过期。{verify_error}"
        if verify_error and ("hostname" in verify_error.lower() or "mismatch" in verify_error.lower()):
            return Severity.FAIL, (
                f"{host} 证书域名不匹配({verify_error})。证书覆盖 {san_list or subject_cn},"
                "与访问域名不符——常见于 SNI 配置错误或用 IP 访问 HTTPS。"
            )
        if verify_error:
            return Severity.WARN, (
                f"{host} 证书校验失败:{verify_error}。可能是自签名、链不全或根证书不受信任,"
                "浏览器会拦截。证书本身:{base}"
            )
        if 0 <= days_left <= 30:
            return Severity.WARN, f"{host} 证书即将过期(剩余 {days_left} 天),请安排续签,否则到期后 HTTPS 将不可用。"
        return Severity.OK, f"{host} 证书有效,校验通过,{base}"
