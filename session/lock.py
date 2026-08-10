"""
session/lock.py — HostLock dataclass and LockManager.

The host lock prevents two machines from simultaneously writing the same world.
It is stored in the remote ``StorageProvider`` (Drive for V1).

Lock record schema (mirrors Drive JSON)::

    {
        "world_id":   "survival",
        "host_id":    "alice-pc-abc123",
        "session_id": "550e8400-e29b-41d4-a716-446655440000",
        "created_at": "2025-01-01T12:00:00+00:00",
        "expires_at": "2025-01-01T13:00:00+00:00"
    }

LockManager usage::

    lm = LockManager(provider=gdrive_provider, config=cfg)
    lock = lm.acquire()          # raises LockConflictError if another host holds it
    try:
        # ... hosting session ...
        lm.refresh(lock)         # call periodically
    finally:
        lm.release(lock)

Design rule: LockManager never starts Minecraft. That responsibility belongs
to Session.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from config.settings import BlockSyncConfig
from storage.provider import (
    LockConflictError,
    LockNotOwnedError,
    StorageProvider,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# HostLock
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class HostLock:
    """Immutable record representing an acquired host lock."""

    world_id:   str
    host_id:    str
    session_id: str
    created_at: datetime   # timezone-aware
    expires_at: datetime   # timezone-aware

    # ── Predicates ────────────────────────────────────────────────────────────

    def is_expired(self) -> bool:
        """Return True if the lock TTL has elapsed."""
        return datetime.now(tz=timezone.utc) >= self.expires_at

    def is_owned_by(self, host_id: str) -> bool:
        """Return True if *host_id* matches this lock's owner."""
        return self.host_id == host_id

    def seconds_until_expiry(self) -> float:
        """Seconds remaining until this lock expires (may be negative)."""
        delta = self.expires_at - datetime.now(tz=timezone.utc)
        return delta.total_seconds()

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "world_id":   self.world_id,
            "host_id":    self.host_id,
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }

    @staticmethod
    def from_dict(d: dict) -> "HostLock":
        def _parse_dt(v) -> datetime:
            dt = datetime.fromisoformat(str(v))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt

        return HostLock(
            world_id=d["world_id"],
            host_id=d["host_id"],
            session_id=d["session_id"],
            created_at=_parse_dt(d["created_at"]),
            expires_at=_parse_dt(d["expires_at"]),
        )

    def __str__(self) -> str:
        remaining = self.seconds_until_expiry()
        return (
            f"HostLock(world={self.world_id!r}, host={self.host_id!r}, "
            f"session={self.session_id[:8]}…, "
            f"{'EXPIRED' if remaining <= 0 else f'{remaining:.0f}s remaining'})"
        )


# ──────────────────────────────────────────────────────────────────────────────
# LockManager
# ──────────────────────────────────────────────────────────────────────────────

class LockManager:
    """Manages host lock acquisition, refresh, and release via a StorageProvider.

    Parameters
    ----------
    provider:
        The storage backend.  Lock read/write goes through this abstraction.
    config:
        Application configuration (world_id, host_id, lock_ttl_seconds).
    """

    def __init__(self, provider: StorageProvider, config: BlockSyncConfig) -> None:
        self._provider = provider
        self._config   = config

    # ── Public API ─────────────────────────────────────────────────────────────

    def acquire(self) -> HostLock:
        """Attempt to acquire the host lock.

        Checks whether a valid, non-expired lock exists for another host.
        If so, raises ``LockConflictError``.  If the existing lock is stale,
        it is overwritten.

        Returns:
            A new ``HostLock`` if acquisition succeeds.

        Raises:
            LockConflictError: If another host currently holds the lock.
            StorageUnavailableError: If Drive cannot be reached.
        """
        existing_raw = self._provider.get_lock(self._config.world_id)

        if existing_raw is not None:
            try:
                existing = HostLock.from_dict(existing_raw)
            except (KeyError, ValueError):
                logger.warning(
                    "Malformed lock on Drive; treating as absent."
                )
                existing = None

            if existing is not None and not existing.is_expired():
                if not existing.is_owned_by(self._config.host_id):
                    raise LockConflictError(existing_raw)
                # We already own a valid lock — this is a re-acquire (e.g. restart).
                logger.info("Re-acquiring our own existing lock: %s", existing)
                # Fall through and overwrite with fresh TTL.

            elif existing is not None and existing.is_expired():
                logger.info(
                    "Overwriting stale lock (was held by %r)", existing.host_id
                )

        now = datetime.now(tz=timezone.utc)
        new_lock = HostLock(
            world_id=self._config.world_id,
            host_id=self._config.host_id,
            session_id=str(uuid.uuid4()),
            created_at=now,
            expires_at=now + timedelta(seconds=self._config.lock_ttl_seconds),
        )

        self._provider.acquire_lock(self._config.world_id, new_lock.to_dict())
        logger.info("Lock acquired: %s", new_lock)
        return new_lock

    def release(self, lock: HostLock) -> None:
        """Release *lock*.

        No-ops gracefully if the lock has already been released (e.g. on
        duplicate cleanup calls).

        Raises:
            LockNotOwnedError: If another session's lock is on Drive.
        """
        try:
            self._provider.release_lock(self._config.world_id, lock.session_id)
            logger.info("Lock released: %s", lock.session_id[:8])
        except LockNotOwnedError:
            logger.error(
                "Tried to release a lock we don't own (session=%s)", lock.session_id
            )
            raise

    def refresh(self, lock: HostLock) -> HostLock:
        """Extend the TTL on an active lock.

        Call this periodically while hosting (e.g. every 30 minutes) to
        prevent expiry.

        Returns:
            A new ``HostLock`` with an updated ``expires_at``.
        """
        now = datetime.now(tz=timezone.utc)
        refreshed = HostLock(
            world_id=lock.world_id,
            host_id=lock.host_id,
            session_id=lock.session_id,
            created_at=lock.created_at,
            expires_at=now + timedelta(seconds=self._config.lock_ttl_seconds),
        )
        self._provider.refresh_lock(
            self._config.world_id, lock.session_id, refreshed.to_dict()
        )
        logger.debug("Lock refreshed: %s", refreshed)
        return refreshed

    def get_current(self) -> Optional[HostLock]:
        """Fetch and parse the current lock from Drive.

        Returns ``None`` if no lock exists or it is malformed.
        """
        raw = self._provider.get_lock(self._config.world_id)
        if raw is None:
            return None
        try:
            return HostLock.from_dict(raw)
        except (KeyError, ValueError):
            logger.warning("Malformed lock data on Drive; returning None")
            return None

    def is_held_by_us(self, lock: HostLock) -> bool:
        """Return True if *lock* matches the current Drive lock."""
        current = self.get_current()
        if current is None:
            return False
        return current.session_id == lock.session_id and not current.is_expired()
