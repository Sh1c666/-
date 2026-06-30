"""HTTP probe tool — the layer that finally answers "network or app?".

A completed HTTP exchange splits the world cleanly:

* 5xx  → the server got the request and failed → **hand the incident back to the app team**
* 4xx  → request reached the app → client/auth/routing issue, not the network
* slow-but-200 → compare against TCP RTT: if TCP is fast but HTTP is slow,
  the app is the bottleneck (DB, GC, slow handler), not the wire
* everything healthy → the fault is almost certainly on the client machine
  (proxy / hosts / local firewall / stale cache)
"""

from __future__ import annotations

from typing import Any

import httpx

from .base import Severity, Tool, ToolResult, _Timer


class HttpProbeTool(Tool):
    name = "http_probe"
    description = (
        "对 URL 发起 HTTP(S) 请求,获取状态码、延迟、重定向链与响应头。"
        "用于在网络层(DNS/连通性/端口/TLS)都正常后,判断到底是服务端(5xx)、客户端(4xx)、"
        "应用慢还是本机问题。是'甩锅'与'定责'的关键一步。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "完整 URL,如 https://example.com/path"},
            "method": {"type": "string", "enum": ["GET", "HEAD"], "default": "GET"},
            "timeout": {"type": "number", "description": "整体超时秒数,默认 10", "default": 10},
            "follow_redirects": {"type": "boolean", "default": True},
        },
        "required": ["url"],
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        url = str(kwargs.get("url", "")).strip()
        method = str(kwargs.get("method", "GET")).upper()
        timeout = float(kwargs.get("timeout", 10))
        follow = bool(kwargs.get("follow_redirects", True))
        if not url:
            return ToolResult(tool=self.name, ok=False, error="缺少参数 url")
        if not url.startswith(("http://", "https://")):
            url = "http://" + url

        redirect_chain: list[dict[str, Any]] = []

        def log_redirect(req: httpx.Request) -> None:
            redirect_chain.append({"url": str(req.url)})

        with _Timer() as t:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=follow,
                verify=True,
            ) as client:
                try:
                    resp = await client.request(method, url)
                except httpx.ConnectError as e:
                    return ToolResult(
                        tool=self.name,
                        severity=Severity.FAIL,
                        summary_zh=(
                            f"HTTP 连接失败:{e}。TCP 层未能建立连接——结合前面 ping/tcp_ping 结果:"
                            "若它们也失败 → 链路/端口问题;若它们成功 → 可能是 SNI/Host 头或代理问题。"
                        ),
                        data={"url": url, "status": "CONNECT_ERROR", "error": str(e)},
                        duration_ms=t.ms,
                    )
                except httpx.ConnectTimeout:
                    return ToolResult(
                        tool=self.name,
                        severity=Severity.FAIL,
                        summary_zh=f"HTTP 连接超时({timeout}s)。TCP 握手未完成,目标端口可能被拦或不通。",
                        data={"url": url, "status": "CONNECT_TIMEOUT"},
                        duration_ms=t.ms,
                    )
                except httpx.ReadTimeout:
                    return ToolResult(
                        tool=self.name,
                        severity=Severity.WARN,
                        summary_zh=(
                            f"HTTP 连接已建立但读取响应超时({timeout}s)。TCP/TLS 正常,"
                            "但服务端响应慢或无响应——倾向应用层问题(后端卡死/慢查询)。"
                        ),
                        data={"url": url, "status": "READ_TIMEOUT"},
                        duration_ms=t.ms,
                    )
                except httpx.HTTPError as e:
                    return ToolResult(
                        tool=self.name,
                        ok=False,
                        error=f"{type(e).__name__}: {e}",
                        summary_zh=f"HTTP 探测异常:{type(e).__name__}。",
                        data={"url": url, "status": type(e).__name__, "error": str(e)},
                        duration_ms=t.ms,
                    )

        status = resp.status_code
        latency = resp.elapsed.total_seconds() * 1000.0
        server = resp.headers.get("server", "")
        ctype = resp.headers.get("content-type", "")
        body_len = len(resp.content)

        severity, summary = self._judge(status, latency, follow, resp.url)
        return ToolResult(
            tool=self.name,
            severity=severity,
            summary_zh=summary,
            data={
                "url": url,
                "final_url": str(resp.url),
                "method": method,
                "status_code": status,
                "latency_ms": round(latency, 1),
                "server": server,
                "content_type": ctype,
                "body_bytes": body_len,
                "redirects": [str(r.url) for r in resp.history],
                "redirect_chain": redirect_chain,
            },
            duration_ms=t.ms,
        )

    def _judge(self, status: int, latency_ms: float, followed: bool, final_url: Any) -> tuple[Severity, str]:
        base = f"HTTP {status}, 延迟 {latency_ms:.0f}ms, 终点 {final_url}."
        if 500 <= status <= 599:
            return (
                Severity.FAIL,
                f"{base} 服务端返回 5xx——请求已到达后端,但服务内部出错。"
                "**网络正常,问题在应用侧**,建议把工单转给应用/后端团队。",
            )
        if 400 <= status <= 499:
            return (
                Severity.WARN,
                f"{base} 服务端返回 {status}——请求到达应用,但被拒绝(权限/路由/参数)。属于客户端或应用配置问题,非网络链路。",
            )
        if status in (301, 302, 307, 308) and not followed:
            return Severity.INFO, f"{base} 重定向(未跟随)。如非预期,检查反向代理/路由配置。"
        if latency_ms > 2000:
            return (
                Severity.WARN,
                f"{base} 响应偏慢。若前面 TCP/TLS RTT 正常,则瓶颈在应用处理(数据库/慢逻辑)而非网络。",
            )
        return Severity.OK, f"{base} 请求成功完成。网络与 TLS 各层均正常——若用户仍报障,排查方向应转向客户端本机(代理/hosts/缓存/本地防火墙)。"
