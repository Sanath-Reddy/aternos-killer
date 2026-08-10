"""
core/session_service.py — Public session API for Developer 2.

Developer 2 (UI/network) must ONLY call this service.
They must NOT touch Session, LockManager, or SessionFSM directly.

All return values are plain Python dicts/strings/None for easy JSON
serialisation and UI binding.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from session.session import Session, SessionError
from session.state import SessionState
from storage.provider import LockConflictError

logger = logging.getLogger(__name__)


class SessionService:
    """High-level session control surface for the UI layer.

    Instantiated once per application run and passed to the UI.

    Parameters
    ----------
    session:
        The underlying ``Session`` orchestrator (injected).
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    # ── State ─────────────────────────────────────────────────────────────────

    def get_state(self) -> str:
        """Return the current session state as a string.

        One of: ``"closed"``, ``"starting"``, ``"active"``, ``"saving"``,
        ``"snapshotting"``, ``"uploading"``, ``"error"``.
        """
        return self._session.get_state().value

    def get_lock_info(self) -> Optional[Dict[str, Any]]:
        """Return the current host lock as a dict, or None if unlocked.

        Example::

            {
                "world_id":   "survival",
                "host_id":    "alice-pc-abc123",
                "session_id": "550e8400...",
                "created_at": "2025-01-01T12:00:00+00:00",
                "expires_at": "2025-01-01T13:00:00+00:00",
                "seconds_remaining": 3598.2
            }
        """
        lock = self._session.get_lock()
        if lock is None:
            return None
        d = lock.to_dict()
        d["seconds_remaining"] = lock.seconds_until_expiry()
        return d

    # ── Actions ───────────────────────────────────────────────────────────────

    def begin_host(self) -> Dict[str, Any]:
        """Acquire the host role, sync the world, and start Minecraft.

        Returns a result dict::

            {"ok": True,  "state": "active"}
            {"ok": False, "error": "<message>", "state": "error"}
        """
        try:
            self._session.begin_host()
            return {"ok": True, "state": self.get_state()}
        except LockConflictError as exc:
            return {
                "ok": False,
                "error": str(exc),
                "error_type": "lock_conflict",
                "state": self.get_state(),
            }
        except Exception as exc:
            logger.error("begin_host error: %s", exc, exc_info=True)
            return {
                "ok": False,
                "error": str(exc),
                "error_type": type(exc).__name__,
                "state": self.get_state(),
            }

    def end_host(self) -> Dict[str, Any]:
        """Save, snapshot, upload, and release the host role.

        Returns a result dict::

            {"ok": True,  "state": "closed",  "version": 185}
            {"ok": False, "error": "<message>", "state": "error"}
        """
        try:
            self._session.end_host()
            manifest = self._session.get_last_manifest()
            return {
                "ok": True,
                "state": self.get_state(),
                "version": manifest.version if manifest else None,
            }
        except Exception as exc:
            logger.error("end_host error: %s", exc, exc_info=True)
            return {
                "ok": False,
                "error": str(exc),
                "error_type": type(exc).__name__,
                "state": self.get_state(),
            }

    def reset_error(self) -> None:
        """Transition from ERROR → CLOSED to allow retrying begin_host."""
        self._session.reset_error()

    def add_state_observer(self, callback) -> None:
        """Register a callback for state changes.

        Signature: ``callback(old_state: str, new_state: str)``

        Wraps the raw ``SessionState`` callback so the UI receives strings.
        """
        def _wrapped(old, new):
            callback(old.value, new.value)
        self._session.add_state_observer(_wrapped)
