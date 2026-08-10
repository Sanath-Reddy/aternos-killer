"""
tests/test_lock.py — Unit tests for HostLock and LockManager.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from session.lock import HostLock, LockManager
from storage.provider import LockConflictError, LockNotOwnedError


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def make_lock(
    host_id="alice-pc",
    session_id="session-abc",
    world_id="survival",
    offset_seconds=3600,
) -> HostLock:
    now = datetime.now(tz=timezone.utc)
    return HostLock(
        world_id=world_id,
        host_id=host_id,
        session_id=session_id,
        created_at=now,
        expires_at=now + timedelta(seconds=offset_seconds),
    )


def make_config(host_id="alice-pc", world_id="survival", ttl=3600):
    cfg = MagicMock()
    cfg.host_id = host_id
    cfg.world_id = world_id
    cfg.lock_ttl_seconds = ttl
    return cfg


# ──────────────────────────────────────────────────────────────────────────────
# HostLock predicates
# ──────────────────────────────────────────────────────────────────────────────

class TestHostLockPredicates:
    def test_not_expired_within_ttl(self):
        lock = make_lock(offset_seconds=3600)
        assert not lock.is_expired()

    def test_expired_when_ttl_in_past(self):
        lock = make_lock(offset_seconds=-1)
        assert lock.is_expired()

    def test_owned_by_correct_host(self):
        lock = make_lock(host_id="alice-pc")
        assert lock.is_owned_by("alice-pc")

    def test_not_owned_by_other_host(self):
        lock = make_lock(host_id="alice-pc")
        assert not lock.is_owned_by("bob-pc")

    def test_seconds_until_expiry_positive(self):
        lock = make_lock(offset_seconds=100)
        assert lock.seconds_until_expiry() > 0

    def test_seconds_until_expiry_negative_when_expired(self):
        lock = make_lock(offset_seconds=-50)
        assert lock.seconds_until_expiry() < 0


# ──────────────────────────────────────────────────────────────────────────────
# HostLock serialisation
# ──────────────────────────────────────────────────────────────────────────────

class TestHostLockSerialization:
    def test_roundtrip(self):
        lock = make_lock()
        lock2 = HostLock.from_dict(lock.to_dict())
        assert lock == lock2

    def test_from_dict_naive_datetime_gets_utc(self):
        d = make_lock().to_dict()
        # Strip timezone from one field.
        d["created_at"] = "2025-01-01T12:00:00"
        lock = HostLock.from_dict(d)
        assert lock.created_at.tzinfo is not None


# ──────────────────────────────────────────────────────────────────────────────
# LockManager.acquire
# ──────────────────────────────────────────────────────────────────────────────

class TestLockManagerAcquire:
    def test_acquire_when_no_existing_lock(self):
        provider = MagicMock()
        provider.get_lock.return_value = None
        provider.acquire_lock.return_value = None

        lm = LockManager(provider, make_config())
        lock = lm.acquire()

        assert lock.host_id == "alice-pc"
        assert lock.world_id == "survival"
        assert not lock.is_expired()
        provider.acquire_lock.assert_called_once()

    def test_acquire_overwrites_stale_lock(self):
        stale = make_lock(host_id="bob-pc", offset_seconds=-1)  # expired
        provider = MagicMock()
        provider.get_lock.return_value = stale.to_dict()
        provider.acquire_lock.return_value = None

        lm = LockManager(provider, make_config(host_id="alice-pc"))
        lock = lm.acquire()

        assert lock.host_id == "alice-pc"

    def test_acquire_raises_on_valid_foreign_lock(self):
        foreign = make_lock(host_id="bob-pc", session_id="bob-session", offset_seconds=3600)
        provider = MagicMock()
        provider.get_lock.return_value = foreign.to_dict()

        lm = LockManager(provider, make_config(host_id="alice-pc"))
        with pytest.raises(LockConflictError):
            lm.acquire()

    def test_reacquire_our_own_valid_lock(self):
        our_lock = make_lock(host_id="alice-pc", session_id="same-session", offset_seconds=3600)
        provider = MagicMock()
        provider.get_lock.return_value = our_lock.to_dict()
        provider.acquire_lock.return_value = None

        lm = LockManager(provider, make_config(host_id="alice-pc"))
        # Should not raise — we own the lock.
        new_lock = lm.acquire()
        assert new_lock.host_id == "alice-pc"

    def test_acquire_gives_unique_session_ids(self):
        provider = MagicMock()
        provider.get_lock.return_value = None
        provider.acquire_lock.return_value = None

        lm = LockManager(provider, make_config())
        lock1 = lm.acquire()
        lock2 = lm.acquire()
        assert lock1.session_id != lock2.session_id


# ──────────────────────────────────────────────────────────────────────────────
# LockManager.release
# ──────────────────────────────────────────────────────────────────────────────

class TestLockManagerRelease:
    def test_release_calls_provider(self):
        provider = MagicMock()
        provider.release_lock.return_value = None

        lm = LockManager(provider, make_config())
        lock = make_lock()
        lm.release(lock)
        provider.release_lock.assert_called_once_with("survival", lock.session_id)

    def test_release_propagates_not_owned_error(self):
        provider = MagicMock()
        provider.release_lock.side_effect = LockNotOwnedError("not yours")

        lm = LockManager(provider, make_config())
        lock = make_lock()
        with pytest.raises(LockNotOwnedError):
            lm.release(lock)


# ──────────────────────────────────────────────────────────────────────────────
# LockManager.refresh
# ──────────────────────────────────────────────────────────────────────────────

class TestLockManagerRefresh:
    def test_refresh_extends_expiry(self):
        provider = MagicMock()
        provider.refresh_lock.return_value = None

        lock = make_lock(offset_seconds=10)  # nearly expired
        lm = LockManager(provider, make_config(ttl=3600))
        refreshed = lm.refresh(lock)

        assert refreshed.seconds_until_expiry() > 3000  # got a fresh TTL
        assert refreshed.session_id == lock.session_id  # same session

    def test_refresh_calls_provider(self):
        provider = MagicMock()
        provider.refresh_lock.return_value = None

        lm = LockManager(provider, make_config())
        lock = make_lock()
        lm.refresh(lock)
        provider.refresh_lock.assert_called_once()


# ──────────────────────────────────────────────────────────────────────────────
# LockManager.get_current
# ──────────────────────────────────────────────────────────────────────────────

class TestLockManagerGetCurrent:
    def test_returns_none_when_no_lock(self):
        provider = MagicMock()
        provider.get_lock.return_value = None
        lm = LockManager(provider, make_config())
        assert lm.get_current() is None

    def test_returns_lock_when_present(self):
        lock = make_lock()
        provider = MagicMock()
        provider.get_lock.return_value = lock.to_dict()
        lm = LockManager(provider, make_config())
        current = lm.get_current()
        assert current == lock

    def test_returns_none_on_malformed_lock(self):
        provider = MagicMock()
        provider.get_lock.return_value = {"broken": True}
        lm = LockManager(provider, make_config())
        assert lm.get_current() is None
