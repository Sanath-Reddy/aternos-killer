"""Tests for Radmin VPN detection helpers (no live adapter required)."""

from network.radmin import RadminNetworkManager, StaticNetworkManager


def test_parse_ipconfig_finds_radmin_ipv4():
    sample = """
Windows IP Configuration

Ethernet adapter Ethernet:

   Connection-specific DNS Suffix  . :
   IPv4 Address. . . . . . . . . . . : 192.168.1.10
   Subnet Mask . . . . . . . . . . . : 255.255.255.0

Ethernet adapter Radmin VPN:

   Connection-specific DNS Suffix  . :
   IPv4 Address. . . . . . . . . . . : 26.45.12.8
   Subnet Mask . . . . . . . . . . . : 255.0.0.0
"""
    adapter, ip = RadminNetworkManager._parse_ipconfig(sample)
    assert adapter == "Radmin VPN"
    assert ip == "26.45.12.8"


def test_parse_ipconfig_missing_radmin():
    sample = """
Ethernet adapter Ethernet:

   IPv4 Address. . . . . . . . . . . : 192.168.1.10
"""
    adapter, ip = RadminNetworkManager._parse_ipconfig(sample)
    assert adapter is None
    assert ip is None


def test_static_network_manager_connected():
    net = StaticNetworkManager(connected=True, ip="10.1.2.3")
    status = net.get_network_status()
    assert status.connected is True
    assert status.ip == "10.1.2.3"
    assert status.provider == "radmin"


def test_static_network_manager_disconnected():
    net = StaticNetworkManager(connected=False)
    status = net.get_network_status()
    assert status.connected is False
    assert status.ip is None
    assert "Radmin" in status.message
