"""
network/radmin.py — Detect the Radmin VPN adapter and its IPv4 address.

Windows-first V1. Uses PowerShell Get-NetIPConfiguration when available,
with an ipconfig fallback. Never hardcodes 26.x.x.x addresses.
"""

from __future__ import annotations

import logging
import platform
import re
import subprocess
import time
from typing import Optional, Tuple

from network.manager import NetworkManager, NetworkStatus

logger = logging.getLogger(__name__)

_RADMIN_NAME_HINT = "radmin vpn"
_IPV4_RE = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\b"
)


class RadminNetworkManager(NetworkManager):
    """Radmin VPN detection via Windows network APIs / commands."""

    provider_name = "radmin"

    def __init__(self) -> None:
        self._cached_result: Optional[Tuple[Optional[str], Optional[str]]] = None
        self._cached_time: float = 0.0

    def is_available(self) -> bool:
        return self.get_ip() is not None

    def get_adapter_name(self) -> Optional[str]:
        adapter, _ = self._detect()
        return adapter

    def get_ip(self) -> Optional[str]:
        _, ip = self._detect()
        return ip

    def get_network_status(self) -> NetworkStatus:
        adapter, ip = self._detect()
        if ip:
            return NetworkStatus(
                provider=self.provider_name,
                connected=True,
                ip=ip,
                adapter_name=adapter,
                message="Connected",
            )
        if platform.system().lower() != "windows":
            return NetworkStatus(
                provider=self.provider_name,
                connected=False,
                ip=None,
                adapter_name=None,
                message="Radmin detection is Windows-only in V1.",
            )
        return NetworkStatus(
            provider=self.provider_name,
            connected=False,
            ip=None,
            adapter_name=adapter,
            message="Install/connect Radmin VPN before hosting.",
        )

    # ── Detection ─────────────────────────────────────────────────────────────

    def _detect(self) -> Tuple[Optional[str], Optional[str]]:
        if platform.system().lower() != "windows":
            return None, None

        now = time.time()
        if self._cached_result is not None and (now - self._cached_time) < 5.0:
            return self._cached_result

        last_adapter: Optional[str] = None
        for detector in (self._detect_ipconfig, self._detect_powershell):
            try:
                adapter, ip = detector()
                if ip:
                    res = (adapter, ip)
                    self._cached_result = res
                    self._cached_time = now
                    return res
                if adapter:
                    last_adapter = adapter
            except Exception as exc:
                logger.debug("Radmin detector failed: %s", exc)

        res = (last_adapter, None)
        self._cached_result = res
        self._cached_time = now
        return res

    def _detect_powershell(self) -> Tuple[Optional[str], Optional[str]]:
        """Use Get-NetIPConfiguration to find Radmin VPN IPv4."""
        script = (
            "$cfg = Get-NetIPConfiguration -ErrorAction SilentlyContinue | "
            "Where-Object { $_.InterfaceAlias -match 'Radmin' }; "
            "if ($cfg) { "
            "  $ip = ($cfg | ForEach-Object { $_.IPv4Address.IPAddress } | "
            "         Where-Object { $_ } | Select-Object -First 1); "
            "  $alias = ($cfg | Select-Object -First 1).InterfaceAlias; "
            "  Write-Output ($alias + '|' + $ip) "
            "}"
        )
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        line = (completed.stdout or "").strip().splitlines()
        if not line:
            return None, None
        parts = line[0].split("|", 1)
        adapter = parts[0].strip() or None
        ip = parts[1].strip() if len(parts) > 1 else ""
        if ip and _IPV4_RE.fullmatch(ip) and not ip.startswith("127."):
            return adapter, ip
        return adapter, None

    def _detect_ipconfig(self) -> Tuple[Optional[str], Optional[str]]:
        """Parse ``ipconfig`` output for an adapter whose name contains Radmin VPN."""
        completed = subprocess.run(
            ["ipconfig"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        text = completed.stdout or ""
        return self._parse_ipconfig(text)

    @staticmethod
    def _parse_ipconfig(text: str) -> Tuple[Optional[str], Optional[str]]:
        adapter: Optional[str] = None
        adapter_is_radmin = False
        pending_adapter: Optional[str] = None

        for raw in text.splitlines():
            line = raw.rstrip()
            # Adapter headers look like: "Ethernet adapter Radmin VPN:"
            if line and not line.startswith(" ") and line.endswith(":"):
                name = line[:-1]
                # Strip leading "Ethernet adapter " / "Wireless LAN adapter " etc.
                for prefix in (
                    "Ethernet adapter ",
                    "Wireless LAN adapter ",
                    "PPP adapter ",
                    "Unknown adapter ",
                ):
                    if name.startswith(prefix):
                        name = name[len(prefix) :]
                        break
                pending_adapter = name
                adapter_is_radmin = _RADMIN_NAME_HINT in name.lower()
                if adapter_is_radmin:
                    adapter = name
                continue

            if not adapter_is_radmin:
                continue

            # IPv4 lines: "   IPv4 Address. . . . . . . . . . . : 26.x.x.x"
            if "IPv4" in line or "IP Address" in line:
                match = _IPV4_RE.search(line)
                if match:
                    ip = match.group(0)
                    if not ip.startswith("127."):
                        return adapter or pending_adapter, ip

        return adapter, None


class StaticNetworkManager(NetworkManager):
    """Test/demo network manager with a fixed status."""

    def __init__(
        self,
        *,
        connected: bool = True,
        ip: Optional[str] = "10.0.0.2",
        adapter_name: str = "Radmin VPN",
        provider: str = "radmin",
    ) -> None:
        self._connected = connected
        self._ip = ip if connected else None
        self._adapter = adapter_name
        self._provider = provider

    def is_available(self) -> bool:
        return bool(self._connected and self._ip)

    def get_adapter_name(self) -> Optional[str]:
        return self._adapter if self._connected else None

    def get_ip(self) -> Optional[str]:
        return self._ip

    def get_network_status(self) -> NetworkStatus:
        if self.is_available():
            return NetworkStatus(
                provider=self._provider,
                connected=True,
                ip=self._ip,
                adapter_name=self._adapter,
                message="Connected",
            )
        return NetworkStatus(
            provider=self._provider,
            connected=False,
            ip=None,
            adapter_name=None,
            message="Install/connect Radmin VPN before hosting.",
        )
