"""Traceroute tool — locate where a path breaks or gets congested.

Wraps the OS traceroute command (`tracert` on Windows, `traceroute`/`tracepath`
on POSIX) and turns its free-form text into a structured hop list plus a
``break_at_hop`` verdict — the layer-3 location a connectivity failure points at.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import shutil
import sys
from typing import Any

from .base import Severity, Tool, ToolResult, _Timer

_WIN = sys.platform.startswith("win")


def _command(host: str, max_hops: int) -> list[str]:
    if _WIN:
        return ["tracert", "-d", "-h", str(max_hops), "-w", "1500", host]
    if shutil.which("traceroute"):
        return ["traceroute", "-n", "-m", str(max_hops), "-w", "2", "-q", "1", host]
    return ["tracepath", host]


def _parse_tracert(text: str) -> list[dict[str, Any]]:
    """Windows tracert: `  1     1 ms     1 ms     1 ms  10.0.0.1` or `*  *  *  Request timed out.`"""
    hops: list[dict[str, Any]] = []
    for line in text.splitlines():
        m = re.match(r"\s*(\d+)\s+(.*)", line)
        if not m:
            continue
        idx = int(m[1])
        rest = m[2]
        ip = None
        ip_match = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", rest)
        if ip_match:
            ip = ip_match[1]
        # collect ms values
        times = [float(x) for x in re.findall(r"(\d+)\s*ms", rest)]
        rtt = times[0] if times else None
        hops.append({"n": idx, "ip": ip, "rtt_ms": rtt})
    return hops


def _parse_traceroute(text: str) -> list[dict[str, Any]]:
    """POSIX traceroute: ` 1  10.0.0.1 (10.0.0.1)  1.123 ms  1.456 ms  1.789 ms` or ` 2  * * *`"""
    hops: list[dict[str, Any]] = []
    for line in text.splitlines():
        m = re.match(r"\s*(\d+)\s+(.*)", line)
        if not m:
            continue
        idx = int(m[1])
        rest = m[2].strip()
        if rest.startswith("*"):
            hops.append({"n": idx, "ip": None, "rtt_ms": None})
            continue
        ip_match = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", rest)
        time_match = re.search(r"([\d.]+)\s*ms", rest)
        hops.append(
            {
                "n": idx,
                "ip": ip_match[1] if ip_match else None,
                "rtt_ms": float(time_match[1]) if time_match else None,
            }
        )
    return hops


def _parse_tracepath(text: str) -> list[dict[str, Any]]:
    """tracepath: ` 2  10.0.0.1   0.123ms ...`"""
    hops: list[dict[str, Any]] = []
    for line in text.splitlines():
        m = re.match(r"\s*(\d+)[?:]?\s+(.*)", line)
        if not m:
            continue
        idx = int(m[1])
        rest = m[2].strip()
        if "no reply" in rest or rest.startswith("*"):
            hops.append({"n": idx, "ip": None, "rtt_ms": None})
            continue
        ip_match = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", rest)
        time_match = re.search(r"([\d.]+)\s*ms", rest)
        hops.append(
            {
                "n": idx,
                "ip": ip_match[1] if ip_match else None,
                "rtt_ms": float(time_match[1]) if time_match else None,
            }
        )
    return hops


class TracerouteTool(Tool):
    name = "traceroute"
    description = (
        "追踪到目标的路由路径,定位断点或拥塞发生在第几跳。"
        "当 ping 全不通或丢包严重时使用,用于判断问题出在本机网段、机房、还是运营商链路。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "host": {"type": "string", "description": "目标主机(IP 或域名)"},
            "max_hops": {"type": "integer", "description": "最大跳数,默认 20", "default": 20},
        },
        "required": ["host"],
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        host = str(kwargs.get("host", "")).strip()
        max_hops = int(kwargs.get("max_hops", 20))
        if not host:
            return ToolResult(tool=self.name, ok=False, error="缺少参数 host")

        cmd = _command(host, max_hops)
        # tracert/traceroute can be slow; allow generous overall timeout.
        overall = max(40.0, max_hops * 3.0)
        with _Timer() as t:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=overall)
            except FileNotFoundError:
                return ToolResult(
                    tool=self.name,
                    ok=False,
                    error="系统未找到 tracert/traceroute/tracepath 命令",
                )
            except asyncio.TimeoutError:
                with contextlib.suppress(Exception):
                    proc.kill()  # type: ignore[possibly-undefined]
                return ToolResult(
                    tool=self.name,
                    severity=Severity.WARN,
                    summary_zh=f"traceroute {host} 超过 {overall:.0f}s 仍未完成,路径可能很长或中间设备限速。",
                    data={"host": host, "status": "timeout"},
                    duration_ms=t.ms,
                )

        text = stdout.decode(errors="replace") + "\n" + stderr.decode(errors="replace")

        if _WIN:
            hops = _parse_tracert(text)
        elif "traceroute" in cmd[0]:
            hops = _parse_traceroute(text)
        else:
            hops = _parse_tracepath(text)

        if not hops:
            return ToolResult(
                tool=self.name,
                ok=False,
                error="无法解析 traceroute 输出",
                summary_zh=f"traceroute {host} 运行完成,但输出格式无法识别。原始输出已记录。",
                data={"host": host, "raw": text[:800]},
                duration_ms=t.ms,
            )

        verdict = self._judge(host, hops)
        return ToolResult(
            tool=self.name,
            severity=verdict["severity"],
            summary_zh=verdict["summary"],
            data={
                "host": host,
                "command": " ".join(cmd),
                "hops": hops,
                "hop_count": len(hops),
                "break_at_hop": verdict["break_at_hop"],
                "status": verdict["status"],
            },
            duration_ms=t.ms,
        )

    def _judge(self, host: str, hops: list[dict[str, Any]]) -> dict[str, Any]:
        # Did we reach the destination? Last hop has an IP (not all timeouts).
        reached = bool(hops and hops[-1].get("ip"))
        # First fully-timeout hop after which the path never recovers.
        break_at = None
        for h in hops:
            if h.get("ip") is None and h.get("rtt_ms") is None:
                # check everything after is also dead
                tail = hops[hops.index(h):]
                if all(x.get("ip") is None for x in tail):
                    break_at = h["n"]
                    break

        last_ip = hops[-1].get("ip") if hops else None
        if reached and break_at is None:
            return {
                "severity": Severity.OK,
                "status": "REACHED",
                "break_at_hop": None,
                "summary": (
                    f"路径追踪完成,到达目标 {host}(最后一跳 {last_ip})。"
                    "整条链路在三层可达,断点不在网络路径上。"
                ),
            }
        if break_at is not None:
            before = next((h.get("ip") for h in reversed(hops) if h.get("ip")), "本机")
            return {
                "severity": Severity.FAIL,
                "status": "BROKEN",
                "break_at_hop": break_at,
                "summary": (
                    f"路径在第 {break_at} 跳中断(此后全部超时)。"
                    f"最后可达节点为 {before}。问题大概率在『{before} → 第{break_at}跳』之间"
                    "的链路/设备——可能是中间路由、防火墙或运营商网络。"
                ),
            }
        # partial / mixed
        return {
            "severity": Severity.WARN,
            "status": "PARTIAL",
            "break_at_hop": None,
            "summary": (
                f"路径追踪未明确到达 {host},也未发现干净断点(中间有部分超时)。"
                "可能是中间节点限速/过滤 ICMP,或目标确实不稳定,建议结合丢包率判断。"
            ),
        }
