"""Ping tools — ICMP (via the OS command) and TCP (pure socket).

Why two of them?
    * ``icmp_ping`` measures true hop-by-hop reachability and latency, but many
      modern servers / cloud hosts *block ICMP* while serving TCP just fine.
    * ``tcp_ping`` checks whether a TCP port can be opened and how fast — it
      needs no privileges and is the canonical way to *refute* a false
      "network is down" verdict caused by ICMP filtering.

Telling the difference ("ICMP fails, TCP succeeds ⇒ target filters ping, link
is actually fine") is one of the highest-value judgments the agent makes.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import sys
import time
from typing import Any

from .base import Severity, Tool, ToolResult, _Timer

_WIN = sys.platform.startswith("win")
_MAC = sys.platform == "darwin"


def _build_icmp_command(host: str, count: int, timeout_s: float) -> list[str]:
    """Build a cross-platform ping argv."""
    timeout_ms = int(timeout_s * 1000)
    if _WIN:
        return ["ping", "-n", str(count), "-w", str(timeout_ms), host]
    if _MAC:
        # macOS: -W is milliseconds
        return ["ping", "-c", str(count), "-W", str(timeout_ms), host]
    # Linux/other POSIX: -W is seconds
    return ["ping", "-c", str(count), "-W", str(int(timeout_s)), host]


def _parse_icmp_output(text: str) -> dict[str, Any]:
    """Parse either Windows or POSIX ping output into structured fields."""
    out: dict[str, Any] = {
        "sent": 0,
        "received": 0,
        "loss_pct": 100.0,
        "rtt_min_ms": None,
        "rtt_avg_ms": None,
        "rtt_max_ms": None,
        "unreachable": False,
        "timed_out": False,
    }

    lower = text.lower()
    if "destination host unreachable" in lower or "destination net unreachable" in lower:
        out["unreachable"] = True
    if "request timed out" in lower or "100% packet loss" in lower:
        out["timed_out"] = True

    # --- loss / counts ---
    # Windows: "Packets: Sent = 4, Received = 4, Lost = 0 (0% loss)"
    m = re.search(r"sent\s*=\s*(\d+)[^=]*received\s*=\s*(\d+)[^=]*lost\s*=\s*(\d+)\s*\((\d+)%", lower)
    if m:
        out["sent"], out["received"] = int(m[1]), int(m[2])
        out["loss_pct"] = float(m[4])
    else:
        # POSIX: "4 packets transmitted, 4 received, 0% packet loss"
        m = re.search(r"(\d+)\s+packets transmitted,\s*(\d+)\s+received(?:,.*?(\d+(?:\.\d+)?)%)?\s*packet loss", lower)
        if m:
            out["sent"], out["received"] = int(m[1]), int(m[2])
            loss = float(m[3]) if m[3] else (100.0 if int(m[2]) == 0 else 0.0)
            out["loss_pct"] = loss

    # --- rtt ---
    # Windows: "Minimum = 11ms, Maximum = 13ms, Average = 12ms"
    m = re.search(r"minimum\s*=\s*(\d+)\s*ms.*?maximum\s*=\s*(\d+)\s*ms.*?average\s*=\s*(\d+)\s*ms", lower)
    if m:
        # groups are, in order: Minimum, Maximum, Average
        out["rtt_min_ms"], out["rtt_max_ms"], out["rtt_avg_ms"] = (
            float(m[1]),
            float(m[2]),
            float(m[3]),
        )
    else:
        # POSIX: "rtt min/avg/max/mdev = 11.1/12.4/13.7/0.6 ms"
        m = re.search(r"(?:rtt|round-trip)\s*min/avg/.*?=\s*([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)\s*ms", text)
        if m:
            out["rtt_min_ms"], out["rtt_avg_ms"], out["rtt_max_ms"] = (
                float(m[1]),
                float(m[2]),
                float(m[3]),
            )

    return out


class IcmpPingTool(Tool):
    name = "icmp_ping"
    description = (
        "对目标发起 ICMP ping,测量丢包率与往返延迟(RTT)。注意:许多云主机/防火墙会禁 ICMP,"
        "因此 ping 不通 ≠ 网络不通;若本工具失败,应再用 tcp_ping 复核。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "host": {"type": "string", "description": "目标主机(IP 或域名)"},
            "count": {"type": "integer", "description": "发送包数,默认 4", "default": 4},
            "timeout": {"type": "number", "description": "每个回包等待秒数,默认 2", "default": 2},
        },
        "required": ["host"],
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        host = str(kwargs.get("host", "")).strip()
        count = int(kwargs.get("count", 4))
        timeout = float(kwargs.get("timeout", 2))
        if not host:
            return ToolResult(tool=self.name, ok=False, error="缺少参数 host")

        cmd = _build_icmp_command(host, count, timeout)
        with _Timer() as t:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=count * timeout + 5
                )
            except FileNotFoundError:
                return ToolResult(
                    tool=self.name, ok=False, error="系统未找到 ping 命令"
                )
            except asyncio.TimeoutError:
                # wait_for cancels the await but leaves the subprocess running;
                # kill it or we leak an orphan ping process per timed-out run.
                with contextlib.suppress(Exception):
                    proc.kill()
                return ToolResult(
                    tool=self.name,
                    severity=Severity.FAIL,
                    summary_zh=f"ping {host} 整体超时,目标很可能不可达。",
                    data={"host": host, "status": "timeout", "loss_pct": 100.0},
                    duration_ms=t.ms,
                )

        text = (stdout.decode(errors="replace") + "\n" + stderr.decode(errors="replace"))
        parsed = _parse_icmp_output(text)
        severity, summary = self._judge(host, parsed)
        return ToolResult(
            tool=self.name,
            severity=severity,
            summary_zh=summary,
            data={"host": host, "command": " ".join(cmd), **parsed},
            duration_ms=t.ms,
        )

    def _judge(self, host: str, p: dict[str, Any]) -> tuple[Severity, str]:
        if p["unreachable"]:
            return Severity.FAIL, f"{host} 目标主机不可达(Destination Host Unreachable),本机路由无法到达该网段。"
        loss = p["loss_pct"]
        recv = p["received"]
        avg = p["rtt_avg_ms"]
        if recv == 0 or loss >= 100:
            return (
                Severity.FAIL,
                f"{host} ICMP 完全不通,丢包 100%。可能原因:目标禁 ICMP、链路中断、或主机宕机。"
                "建议立刻用 tcp_ping 复核是否仅 ICMP 被过滤。",
            )
        if loss > 0:
            jitter_note = ""
            return (
                Severity.WARN,
                f"{host} ICMP 存在丢包,丢包率 {loss:.0f}%(收 {recv}/{p['sent']})"
                + (f",平均 RTT {avg:.0f}ms。" if avg else "。")
                + "丢包会导致 TCP 重传与吞吐骤降,即使能 ping 通也会'卡'。"
                + jitter_note,
            )
        rtt_note = f",平均 RTT {avg:.0f}ms,链路正常。" if avg else ",链路正常。"
        return Severity.OK, f"{host} ICMP 正常,0 丢包(收 {recv}/{p['sent']})" + rtt_note


class TcpPingTool(Tool):
    name = "tcp_ping"
    description = (
        "对目标的指定 TCP 端口发起连接探测(免管理员权限),测量 TCP 握手 RTT。"
        "用于复核'ping 不通但端口通'的情况(目标禁 ICMP,链路其实正常)。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "host": {"type": "string", "description": "目标主机(IP 或域名)"},
            "port": {"type": "integer", "description": "目标 TCP 端口,如 80/443/22"},
            "timeout": {"type": "number", "description": "连接超时秒数,默认 3", "default": 3},
        },
        "required": ["host", "port"],
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        host = str(kwargs.get("host", "")).strip()
        port = int(kwargs.get("port", 80))
        timeout = float(kwargs.get("timeout", 3))
        if not host:
            return ToolResult(tool=self.name, ok=False, error="缺少参数 host")

        with _Timer() as t:
            rtt = await self._measure(host, port, timeout)

        if rtt is None:
            return ToolResult(
                tool=self.name,
                severity=Severity.FAIL,
                summary_zh=f"TCP 连接 {host}:{port} 失败。可能:端口未开放/被防火墙拦截/服务未启动。"
                "结合前面 ICMP 结果判断:若 ICMP 也不通 → 链路问题;若仅 TCP 不通 → 端口/防火墙问题。",
                data={"host": host, "port": port, "reachable": False},
                duration_ms=t.ms,
            )

        return ToolResult(
            tool=self.name,
            severity=Severity.OK,
            summary_zh=f"TCP 连接 {host}:{port} 成功,握手 RTT {rtt:.0f}ms,端口可达且服务在监听。",
            data={"host": host, "port": port, "reachable": True, "rtt_ms": round(rtt, 2)},
            duration_ms=t.ms,
        )

    @staticmethod
    async def _measure(host: str, port: int, timeout: float) -> float | None:
        """Open a TCP connection and measure the handshake RTT in ms.

        Pure-asyncio (no executor): earlier versions ran socket code in a thread
        and called ``asyncio.get_event_loop()`` *inside* it, which raises on
        Python 3.12+ because worker threads have no event loop — silently
        turning every tcp_ping into a swallowed exception. ``open_connection``
        sidesteps that entirely.
        """
        start = time.perf_counter()
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=timeout
            )
        except (TimeoutError, asyncio.TimeoutError, OSError):
            return None
        rtt = (time.perf_counter() - start) * 1000.0
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
        return rtt
