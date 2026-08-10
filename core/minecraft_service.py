"""
core/minecraft_service.py — Public Minecraft process API for Developer 2.

The UI can read server status and the log tail.
Commands can also be sent (e.g. for admin actions from the UI).

The UI must NOT call MinecraftManager directly.
"""

from __future__ import annotations

import logging
from typing import Dict, List

from minecraft.manager import MinecraftManager, ProcessStatus

logger = logging.getLogger(__name__)

# Map internal ProcessStatus → user-friendly strings.
_STATUS_LABELS: Dict[str, str] = {
    ProcessStatus.NOT_RUNNING.value: "offline",
    ProcessStatus.STARTING.value:    "starting",
    ProcessStatus.READY.value:       "online",
    ProcessStatus.STOPPING.value:    "stopping",
    ProcessStatus.CRASHED.value:     "crashed",
}


class MinecraftService:
    """Read/command surface for the Minecraft process, exposed to Developer 2.

    Parameters
    ----------
    mc:
        The underlying ``MinecraftManager`` instance.
    """

    def __init__(self, mc: MinecraftManager) -> None:
        self._mc = mc

    def get_status(self) -> str:
        """Return a user-friendly server status string.

        One of: ``"offline"``, ``"starting"``, ``"online"``,
        ``"stopping"``, ``"crashed"``.
        """
        return _STATUS_LABELS.get(self._mc.status.value, "unknown")

    def get_log_tail(self, n: int = 50) -> List[str]:
        """Return the last *n* lines from the Minecraft console log."""
        return self._mc.get_log_lines(n=n)

    def send_command(self, cmd: str) -> Dict[str, bool]:
        """Send a console command to the running Minecraft server.

        Returns ``{"ok": True}`` on success or ``{"ok": False, "error": "..."}``
        if the server is not running.
        """
        try:
            self._mc.send_command(cmd)
            return {"ok": True}
        except Exception as exc:
            logger.error("send_command failed: %s", exc)
            return {"ok": False, "error": str(exc)}

    def is_running(self) -> bool:
        """Return True if the Minecraft process is alive."""
        return self._mc.is_running()
