"""Tests for the diagnostic tools — parsing logic + a local socket scan.

Network-touching tools (DNS/HTTP against the internet) are intentionally not
unit-tested here: they're flaky in CI and depend on egress. We test the pure
parsing/decision logic instead, plus a deterministic loopback port scan.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket

import pytest

from netpilot.tools.ping import _parse_icmp_output
from netpilot.tools.portscan import PortScanTool
from netpilot.tools.traceroute import (
    _parse_tracepath,
    _parse_traceroute,
    _parse_tracert,
)

# --------------------------------------------------------------------------- ICMP
WINDOWS_PING = """\
Pinging example.com [93.184.216.34] with 32 bytes of data:
Reply from 93.184.216.34: bytes=32 time=12ms TTL=56
Reply from 93.184.216.34: bytes=32 time=11ms TTL=56
Reply from 93.184.216.34: bytes=32 time=13ms TTL=56
Reply from 93.184.216.34: bytes=32 time=12ms TTL=56

Ping statistics for 93.184.216.34:
    Packets: Sent = 4, Received = 4, Lost = 0 (0% loss),
Approximate round trip times in milli-seconds:
    Minimum = 11ms, Maximum = 13ms, Average = 12ms
"""

POSIX_PING = """\
PING example.com (93.184.216.34) 56(84) bytes of data.
64 bytes from 93.184.216.34: icmp_seq=1 ttl=56 time=12.1 ms
64 bytes from 93.184.216.34: icmp_seq=2 ttl=56 time=11.8 ms
--- example.com ping statistics ---
4 packets transmitted, 4 received, 0% packet loss, time 3005ms
rtt min/avg/max/mdev = 11.123/12.456/13.789/0.666 ms
"""

POSIX_PING_LOSS = """\
PING host (10.0.0.5) 56(84) bytes of data.
64 bytes from 10.0.0.5: icmp_seq=2 ttl=64 time=5.0 ms
--- host ping statistics ---
4 packets transmitted, 1 received, 75% packet loss
rtt min/avg/max/mdev = 5.0/5.0/5.0/0.0 ms
"""


def test_parse_windows_ping_success():
    p = _parse_icmp_output(WINDOWS_PING)
    assert p["sent"] == 4 and p["received"] == 4
    assert p["loss_pct"] == 0.0
    assert p["rtt_avg_ms"] == 12.0
    assert p["rtt_min_ms"] == 11.0 and p["rtt_max_ms"] == 13.0


def test_parse_posix_ping_success():
    p = _parse_icmp_output(POSIX_PING)
    assert p["sent"] == 4 and p["received"] == 4
    assert p["loss_pct"] == 0.0
    assert p["rtt_avg_ms"] == pytest.approx(12.456, rel=1e-3)


def test_parse_posix_ping_with_loss():
    p = _parse_icmp_output(POSIX_PING_LOSS)
    assert p["received"] == 1
    assert p["loss_pct"] == 75.0


def test_parse_ping_total_loss():
    p = _parse_icmp_output("Reply from 1.2.3.4: Destination host unreachable.")
    assert p["unreachable"] is True


# --------------------------------------------------------------------------- traceroute
TRACERT = """\
Tracing route to example.com [93.184.216.34] over a maximum of 30 hops:
  1     1 ms     1 ms     1 ms  192.168.1.1
  2     5 ms     4 ms     5 ms  10.0.0.1
  3     *        *        *     Request timed out.
  4     *        *        *     Request timed out.

Trace complete.
"""

TRACEROUTE = """\
traceroute to example.com (93.184.216.34), 30 hops max
 1  192.168.1.1 (192.168.1.1)  1.123 ms  1.456 ms  1.789 ms
 2  10.0.0.1 (10.0.0.1)  4.500 ms  4.600 ms  4.700 ms
 3  * * *
 4  * * *
"""

TRACEPATH = """\
 1?: [LOCALHOST]                      pmtu 1500
 1:  192.168.1.1                         1.234ms
 2:  10.0.0.1                            4.500ms
 3:  no reply
"""


def test_parse_tracert_windows():
    hops = _parse_tracert(TRACERT)
    assert len(hops) == 4
    assert hops[0] == {"n": 1, "ip": "192.168.1.1", "rtt_ms": 1.0}
    assert hops[2]["ip"] is None              # timed out
    assert hops[2]["rtt_ms"] is None


def test_parse_traceroute_posix():
    hops = _parse_traceroute(TRACEROUTE)
    assert len(hops) == 4
    assert hops[1]["ip"] == "10.0.0.1"
    assert hops[2]["ip"] is None
    assert hops[2]["rtt_ms"] is None


def test_parse_tracepath():
    hops = _parse_tracepath(TRACEPATH)
    assert hops[1]["ip"] == "10.0.0.1"
    assert any(h["ip"] is None for h in hops)  # the "no reply" line


# --------------------------------------------------------------------------- port spec parsing
def test_parse_ports_presets_and_ranges():
    tool = PortScanTool()
    assert set(tool._parse_ports("web")) == {80, 443, 8080, 8443}
    assert tool._parse_ports("80,443,8080") == [80, 443, 8080]
    assert tool._parse_ports("8000-8003") == [8000, 8001, 8002, 8003]
    # dedup + invalid ignored
    assert tool._parse_ports("80,80,999999,abc,443") == [80, 443]


# --------------------------------------------------------------------------- live loopback scan
@pytest.mark.asyncio
async def test_port_scan_detects_open_and_closed():
    # Open a real listener on an ephemeral loopback port.
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    open_port = srv.getsockname()[1]
    closed_port = open_port + 1 if open_port + 1 < 65535 else open_port - 1

    async def accept_once():
        with contextlib.suppress(OSError):
            await asyncio.get_event_loop().sock_accept(srv)

    srv.setblocking(False)
    acc = asyncio.ensure_future(accept_once())
    try:
        tool = PortScanTool()
        result = await tool.run(host="127.0.0.1", ports=f"{open_port},{closed_port}", timeout=1.0)
        assert result.ok
        assert open_port in result.data["open"]
        # the other one is closed or filtered, never open
        assert closed_port not in result.data["open"]
    finally:
        acc.cancel()
        srv.close()
