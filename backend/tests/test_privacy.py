"""Tests for the privacy/desensitization layer."""

from netpilot.core.privacy import PrivacyMask, _is_sensitive


def test_is_sensitive_classification():
    assert _is_sensitive("10.0.0.5")
    assert _is_sensitive("192.168.1.1")
    assert _is_sensitive("172.16.0.1")
    assert _is_sensitive("127.0.0.1")
    assert _is_sensitive("169.254.1.1")  # link-local
    assert not _is_sensitive("8.8.8.8")
    assert not _is_sensitive("1.1.1.1")
    assert not _is_sensitive("114.114.114.114")
    assert not _is_sensitive("not-an-ip")
    assert not _is_sensitive("999.1.1.1")


def test_mask_replaces_only_private_ips():
    m = PrivacyMask()
    out = m.mask("网关 10.0.0.1, 公网 8.8.8.8, 内网 10.0.0.1")
    assert "10.0.0.1" not in out
    assert "8.8.8.8" in out            # public stays
    assert out.count("[内网IP-1]") == 2  # same IP → same token, used twice


def test_distinct_ips_get_distinct_tokens():
    m = PrivacyMask()
    out = m.mask("10.0.0.1 和 192.168.1.5")
    assert "[内网IP-1]" in out
    assert "[内网IP-2]" in out


def test_round_trip_unmask():
    m = PrivacyMask()
    original = "网关 10.0.0.1, 主机 192.168.1.5, 外网 203.0.113.10"
    masked = m.mask(original)
    assert masked != original
    assert m.unmask(masked) == original


def test_ports_and_versions_not_corrupted():
    """A bare port number or TLS version must not be eaten by the IP masker."""
    m = PrivacyMask()
    text = "端口 443, TLS 1.3, 延迟 12ms, IP 10.0.0.1"
    out = m.mask(text)
    assert "443" in out and "1.3" in out and "12ms" in out
    assert "10.0.0.1" not in out
