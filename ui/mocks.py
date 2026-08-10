"""
ui/mocks.py — Local stand-ins matching core service method shapes.

Used when BLOCKSYNC_USE_MOCKS=1 (default) or when real core wiring fails
(e.g. missing world/ package). Never imports Dev1 internals.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class MockWorldService:
    def __init__(
        self,
        *,
        world_id: str = "Survival",
        local_version: int = 183,
        remote_version: int = 184,
        sync_result: str = "NEEDS_UPDATE",
    ) -> None:
        self._world_id = world_id
        self._local_version = local_version
        self._remote_version = remote_version
        self._sync_result = sync_result
        self._downloading = False
        self._download_pct = 0

    def get_local_manifest(self) -> Optional[Dict[str, Any]]:
        if self._local_version is None:
            return None
        return {
            "world_id": self._world_id,
            "version": self._local_version,
            "parent_version": max(0, self._local_version - 1),
            "snapshot": f"snapshots/world-{self._local_version}.tar.zst",
            "sha256": "a" * 64,
            "minecraft_version": "1.21.4",
            "created_at": "2025-01-01T12:00:00+00:00",
            "created_by": "mock-local",
        }

    def get_remote_manifest(self) -> Optional[Dict[str, Any]]:
        if self._remote_version is None:
            return None
        return {
            "world_id": self._world_id,
            "version": self._remote_version,
            "parent_version": max(0, self._remote_version - 1),
            "snapshot": f"snapshots/world-{self._remote_version}.tar.zst",
            "sha256": "b" * 64,
            "minecraft_version": "1.21.4",
            "created_at": "2025-01-02T12:00:00+00:00",
            "created_by": "alice-pc-mock",
        }

    def compare_versions(self) -> Dict[str, Any]:
        return {
            "result": self._sync_result,
            "local_version": self._local_version,
            "remote_version": self._remote_version,
        }

    def validate_local_world(self) -> bool:
        return True

    def sync_world(self) -> Dict[str, Any]:
        """Mock-only helper for UPDATE WORLD until Dev1 exposes this."""
        self._downloading = True
        self._download_pct = 0
        for pct in (20, 45, 70, 90, 100):
            time.sleep(0.25)
            self._download_pct = pct
        self._local_version = self._remote_version
        self._sync_result = "UP_TO_DATE"
        self._downloading = False
        return {"ok": True, "version": self._local_version}

    def get_download_progress(self) -> int:
        return self._download_pct


class MockMinecraftService:
    def __init__(self) -> None:
        self._status = "offline"
        self._running = False
        self._log: List[str] = [
            "[Server] Mock Minecraft console ready.",
        ]

    def get_status(self) -> str:
        return self._status

    def get_log_tail(self, n: int = 50) -> List[str]:
        return self._log[-n:]

    def send_command(self, cmd: str) -> Dict[str, Any]:
        if not self._running:
            return {"ok": False, "error": "Server is not running."}
        self._log.append(f"> {cmd}")
        return {"ok": True}

    def is_running(self) -> bool:
        return self._running

    # Internal helpers for MockSessionService
    def _start(self) -> None:
        self._status = "starting"
        self._log.append("[Server] Starting minecraft server version 1.21.4")
        time.sleep(0.4)
        self._status = "online"
        self._running = True
        self._log.append('[Server] Done (2.141s)! For help, type "help"')

    def _stop(self) -> None:
        self._status = "stopping"
        self._log.append("[Server] Stopping the server")
        time.sleep(0.3)
        self._status = "offline"
        self._running = False


class MockSessionService:
    def __init__(
        self,
        world: MockWorldService,
        mc: MockMinecraftService,
        *,
        foreign_host: Optional[str] = None,
    ) -> None:
        self._world = world
        self._mc = mc
        self._state = "closed"
        self._lock: Optional[Dict[str, Any]] = None
        self._foreign_host = foreign_host
        self._observers: List[Callable[[str, str], None]] = []
        self._last_error: Optional[str] = None
        self._last_version: Optional[int] = world._local_version
        self._host_id = "you-local-mock"

    def get_state(self) -> str:
        return self._state

    def get_lock_info(self) -> Optional[Dict[str, Any]]:
        if self._lock is not None:
            return dict(self._lock)
        if self._foreign_host and self._state == "closed":
            now = datetime.now(timezone.utc)
            return {
                "world_id": self._world._world_id,
                "host_id": self._foreign_host,
                "session_id": "foreign-session",
                "created_at": now.isoformat(),
                "expires_at": (now + timedelta(hours=1)).isoformat(),
                "seconds_remaining": 3500.0,
            }
        return None

    def begin_host(self) -> Dict[str, Any]:
        if self._foreign_host and self._state == "closed":
            return {
                "ok": False,
                "error": f"Host lock held by {self._foreign_host}",
                "error_type": "lock_conflict",
                "state": self._state,
            }

        try:
            self._set_state("starting")
            time.sleep(0.35)

            compare = self._world.compare_versions()
            result = compare["result"]
            if result == "CONFLICT":
                self._set_state("error")
                return {
                    "ok": False,
                    "error": "Local and remote world histories have diverged.",
                    "error_type": "WorldConflictError",
                    "state": self._state,
                }
            if result == "LOCAL_AHEAD":
                self._set_state("error")
                return {
                    "ok": False,
                    "error": "Local world is newer than the shared world.",
                    "error_type": "LocalWorldAheadError",
                    "state": self._state,
                }
            if result in ("NEEDS_UPDATE", "NO_LOCAL"):
                self._world.sync_world()

            self._mc._start()
            now = datetime.now(timezone.utc)
            self._lock = {
                "world_id": self._world._world_id,
                "host_id": self._host_id,
                "session_id": str(uuid.uuid4()),
                "created_at": now.isoformat(),
                "expires_at": (now + timedelta(hours=1)).isoformat(),
                "seconds_remaining": 3600.0,
            }
            self._foreign_host = None
            self._set_state("active")
            return {"ok": True, "state": self._state}
        except Exception as exc:
            logger.error("Mock begin_host failed: %s", exc)
            self._last_error = str(exc)
            self._set_state("error")
            return {
                "ok": False,
                "error": str(exc),
                "error_type": type(exc).__name__,
                "state": self._state,
            }

    def end_host(self) -> Dict[str, Any]:
        try:
            self._set_state("saving")
            time.sleep(0.35)
            self._mc._stop()
            self._set_state("snapshotting")
            time.sleep(0.3)
            self._set_state("uploading")
            time.sleep(0.4)
            self._last_version = (self._world._local_version or 0) + 1
            self._world._local_version = self._last_version
            self._world._remote_version = self._last_version
            self._world._sync_result = "UP_TO_DATE"
            self._lock = None
            self._set_state("closed")
            return {"ok": True, "state": self._state, "version": self._last_version}
        except Exception as exc:
            self._last_error = str(exc)
            self._set_state("error")
            return {
                "ok": False,
                "error": str(exc),
                "error_type": type(exc).__name__,
                "state": self._state,
            }

    def reset_error(self) -> None:
        if self._state == "error":
            self._set_state("closed")
            self._last_error = None

    def add_state_observer(self, callback: Callable[[str, str], None]) -> None:
        self._observers.append(callback)

    def _set_state(self, new: str) -> None:
        old = self._state
        self._state = new
        for cb in list(self._observers):
            try:
                cb(old, new)
            except Exception as exc:
                logger.debug("Observer error: %s", exc)


def build_default_mocks(
    *,
    foreign_host: Optional[str] = None,
    sync_result: str = "UP_TO_DATE",
    local_version: int = 184,
    remote_version: int = 184,
) -> tuple[MockSessionService, MockWorldService, MockMinecraftService]:
    world = MockWorldService(
        local_version=local_version,
        remote_version=remote_version,
        sync_result=sync_result,
    )
    mc = MockMinecraftService()
    session = MockSessionService(world, mc, foreign_host=foreign_host)
    return session, world, mc
