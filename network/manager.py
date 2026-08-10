"""
network/manager.py — Abstract network connectivity surface for the UI.

Radmin VPN is the V1 implementation. Future providers (WireGuard, etc.)
implement the same NetworkManager contract without UI changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class NetworkStatus:
    """Plain status object for UI binding."""

    provider: str
    connected: bool
    ip: Optional[str]
    adapter_name: Optional[str]
    message: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "connected": self.connected,
            "ip": self.ip,
            "adapter_name": self.adapter_name,
            "message": self.message,
        }


class NetworkManager(ABC):
    """Detect whether friends can reach this machine over the shared VPN."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the VPN adapter is present and has an IPv4 address."""

    @abstractmethod
    def get_adapter_name(self) -> Optional[str]:
        """Return the detected adapter display name, or None."""

    @abstractmethod
    def get_ip(self) -> Optional[str]:
        """Return the VPN IPv4 address, or None if unavailable."""

    @abstractmethod
    def get_network_status(self) -> NetworkStatus:
        """Return a full status snapshot for the UI."""
