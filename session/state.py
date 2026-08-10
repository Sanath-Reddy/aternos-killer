"""
session/state.py — Session state machine.

Defines the set of valid states and legal transitions for a BlockSync host
session.  Invalid transitions raise ``InvalidTransitionError`` immediately so
bugs are caught at the source rather than surfacing as mysterious state
corruption later.

Valid lifecycle::

    CLOSED → STARTING → ACTIVE → SAVING → SNAPSHOTTING → UPLOADING → CLOSED
                                                                    ↘ ERROR (any state)
    ERROR → CLOSED
"""

from __future__ import annotations

import logging
import threading
from enum import Enum
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# State enum
# ──────────────────────────────────────────────────────────────────────────────

class SessionState(Enum):
    """Enumeration of all possible host-session states."""

    CLOSED = "closed"
    """No active session. The app is idle."""

    STARTING = "starting"
    """Lock acquired; world validated; Minecraft process launching."""

    ACTIVE = "active"
    """Minecraft is running and ready. Players can connect."""

    SAVING = "saving"
    """``save-all flush`` sent; waiting for confirmation before stopping."""

    SNAPSHOTTING = "snapshotting"
    """Minecraft stopped; creating and hashing the snapshot archive."""

    UPLOADING = "uploading"
    """Snapshot verified locally; uploading to Google Drive."""

    ERROR = "error"
    """A non-recoverable error occurred. Must transition to CLOSED to retry."""


# ──────────────────────────────────────────────────────────────────────────────
# Exceptions
# ──────────────────────────────────────────────────────────────────────────────

class InvalidTransitionError(Exception):
    """Raised when a state transition is not permitted."""

    def __init__(self, from_state: SessionState, to_state: SessionState) -> None:
        super().__init__(
            f"Invalid session transition: {from_state.value!r} → {to_state.value!r}"
        )
        self.from_state = from_state
        self.to_state = to_state


# ──────────────────────────────────────────────────────────────────────────────
# Transition table
# ──────────────────────────────────────────────────────────────────────────────

# Every state lists which states it may legally transition INTO.
_TRANSITIONS: Dict[SessionState, List[SessionState]] = {
    SessionState.CLOSED: [
        SessionState.STARTING,
    ],
    SessionState.STARTING: [
        SessionState.ACTIVE,
        SessionState.ERROR,
    ],
    SessionState.ACTIVE: [
        SessionState.SAVING,
        SessionState.ERROR,
    ],
    SessionState.SAVING: [
        SessionState.SNAPSHOTTING,
        SessionState.ERROR,
    ],
    SessionState.SNAPSHOTTING: [
        SessionState.UPLOADING,
        SessionState.ERROR,
    ],
    SessionState.UPLOADING: [
        SessionState.CLOSED,
        SessionState.ERROR,
    ],
    SessionState.ERROR: [
        SessionState.CLOSED,
    ],
}


# ──────────────────────────────────────────────────────────────────────────────
# SessionFSM
# ──────────────────────────────────────────────────────────────────────────────

StateChangeCallback = Callable[[SessionState, SessionState], None]
"""Signature: ``callback(old_state, new_state)``."""


class SessionFSM:
    """Thread-safe finite state machine for a BlockSync host session.

    Usage::

        fsm = SessionFSM()
        fsm.transition(SessionState.STARTING)
        # ... start Minecraft ...
        fsm.transition(SessionState.ACTIVE)

    Observers can subscribe to state changes::

        def on_change(old, new):
            print(f"State: {old.value} → {new.value}")

        fsm.add_observer(on_change)
    """

    def __init__(self, initial: SessionState = SessionState.CLOSED) -> None:
        self._state: SessionState = initial
        self._lock = threading.Lock()
        self._observers: List[StateChangeCallback] = []

    # ── Public interface ──────────────────────────────────────────────────────

    @property
    def state(self) -> SessionState:
        """Current state (thread-safe read)."""
        with self._lock:
            return self._state

    def transition(self, new_state: SessionState) -> None:
        """Attempt a state transition.

        Raises:
            InvalidTransitionError: If the transition is not in the
                allowed set for the current state.
        """
        with self._lock:
            old_state = self._state
            allowed = _TRANSITIONS.get(old_state, [])
            if new_state not in allowed:
                raise InvalidTransitionError(old_state, new_state)
            self._state = new_state

        logger.info(
            "Session state: %s → %s",
            old_state.value,
            new_state.value,
        )
        self._notify(old_state, new_state)

    def force_error(self, reason: str = "") -> None:
        """Unconditionally move to ERROR from any state.

        Use only when a non-recoverable failure has occurred and the normal
        transition table would block the move (e.g. CLOSED → ERROR is not a
        valid normal path but may be needed during startup failures).
        """
        with self._lock:
            old_state = self._state
            if old_state == SessionState.ERROR:
                return  # already in error; no-op
            self._state = SessionState.ERROR

        logger.error(
            "Session forced to ERROR from %s%s",
            old_state.value,
            f": {reason}" if reason else "",
        )
        self._notify(old_state, SessionState.ERROR)

    def add_observer(self, callback: StateChangeCallback) -> None:
        """Register a callback invoked on every state change."""
        self._observers.append(callback)

    def remove_observer(self, callback: StateChangeCallback) -> None:
        """Unregister a previously added callback."""
        try:
            self._observers.remove(callback)
        except ValueError:
            pass

    def can_transition_to(self, state: SessionState) -> bool:
        """Return True if transitioning to *state* is currently legal."""
        with self._lock:
            return state in _TRANSITIONS.get(self._state, [])

    # ── Private ───────────────────────────────────────────────────────────────

    def _notify(self, old: SessionState, new: SessionState) -> None:
        for cb in list(self._observers):
            try:
                cb(old, new)
            except Exception:
                logger.exception("Observer raised an exception")

    # ── Repr ──────────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return f"SessionFSM(state={self._state.value!r})"
