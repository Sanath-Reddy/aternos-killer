"""
storage/provider.py — StorageProvider abstract base class.

All storage operations go through this interface.  The rest of the application
depends ONLY on this abstraction — never on ``gdrive.py`` directly.

Implementing a new backend (e.g. S3, MinIO, a custom server) means creating a
new class that inherits from ``StorageProvider`` and wiring it through
``BlockSyncConfig``.

Lock semantics
--------------
Locks are represented as plain dicts matching the HostLock schema::

    {
        "world_id":   "survival",
        "host_id":    "alice-pc-abc123",
        "session_id": "550e8400-e29b-41d4-a716-446655440000",
        "created_at": "2025-01-01T12:00:00+00:00",
        "expires_at": "2025-01-01T13:00:00+00:00"
    }

``acquire_lock()`` MUST be atomic from the caller's perspective: it either
succeeds exclusively or raises ``LockConflictError`` without side effects.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


# ──────────────────────────────────────────────────────────────────────────────
# Exceptions
# ──────────────────────────────────────────────────────────────────────────────

class StorageError(RuntimeError):
    """Base class for storage operation failures."""


class StorageUnavailableError(StorageError):
    """Raised when the storage backend cannot be reached."""


class ManifestNotFoundError(StorageError):
    """Raised when no manifest exists in the storage backend."""


class SnapshotNotFoundError(StorageError):
    """Raised when the requested snapshot does not exist on storage."""


class LockConflictError(StorageError):
    """Raised when a valid lock held by another host prevents acquisition."""

    def __init__(self, existing_lock: dict) -> None:
        host = existing_lock.get("host_id", "unknown")
        expires = existing_lock.get("expires_at", "?")
        super().__init__(
            f"World is locked by {host!r} until {expires}. "
            "Wait for them to finish or for the lock to expire."
        )
        self.existing_lock = existing_lock


class LockNotOwnedError(StorageError):
    """Raised when releasing or refreshing a lock that isn't yours."""


class UploadError(StorageError):
    """Raised when a snapshot upload fails."""


class DownloadError(StorageError):
    """Raised when a snapshot download or verification fails."""


# ──────────────────────────────────────────────────────────────────────────────
# StorageProvider ABC
# ──────────────────────────────────────────────────────────────────────────────

class StorageProvider(ABC):
    """Abstract interface for BlockSync remote storage operations.

    Implementations must be safe to call from a single thread.
    All methods should raise subclasses of ``StorageError`` on failure.
    """

    # ── Manifest ──────────────────────────────────────────────────────────────

    @abstractmethod
    def get_manifest(self) -> Optional[dict]:
        """Fetch the world manifest from remote storage.

        Returns:
            The manifest as a raw dict, or ``None`` if no manifest exists
            yet (first-time setup).

        Raises:
            StorageUnavailableError: If the backend cannot be reached.
            StorageError: On unexpected errors.
        """
        ...

    @abstractmethod
    def update_manifest(self, manifest: dict) -> None:
        """Atomically replace the remote manifest with *manifest*.

        Must only be called after the corresponding snapshot has been
        successfully uploaded and verified.

        Raises:
            StorageUnavailableError: If the backend cannot be reached.
            StorageError: On unexpected errors.
        """
        ...

    # ── Snapshots ─────────────────────────────────────────────────────────────

    @abstractmethod
    def upload_snapshot(
        self,
        local_path: Path,
        remote_name: str,
    ) -> str:
        """Upload the snapshot archive at *local_path* to remote storage.

        Parameters
        ----------
        local_path:
            Absolute path to the local ``.tar.zst`` file.
        remote_name:
            Desired filename on the remote backend (e.g. ``world-185.tar.zst``).

        Returns:
            The confirmed remote path / identifier (provider-specific).

        Raises:
            UploadError: If the upload fails or the remote hash doesn't match.
            StorageUnavailableError: If the backend cannot be reached.
        """
        ...

    @abstractmethod
    def download_snapshot(
        self,
        remote_name: str,
        dest: Path,
        expected_sha256: str,
    ) -> None:
        """Download a snapshot from remote storage to *dest*.

        Verifies the SHA-256 hash after download.

        Parameters
        ----------
        remote_name:
            The filename on the remote backend.
        dest:
            Absolute path where the file should be written.
        expected_sha256:
            64-char hex digest; ``DownloadError`` is raised if the downloaded
            file doesn't match.

        Raises:
            SnapshotNotFoundError: If the remote snapshot does not exist.
            DownloadError: If the download fails or hash verification fails.
            StorageUnavailableError: If the backend cannot be reached.
        """
        ...

    # ── Host Lock ─────────────────────────────────────────────────────────────

    @abstractmethod
    def get_lock(self, world_id: str) -> Optional[dict]:
        """Fetch the current host lock for *world_id*.

        Returns:
            The lock as a raw dict, or ``None`` if no lock exists.

        Raises:
            StorageUnavailableError: If the backend cannot be reached.
        """
        ...

    @abstractmethod
    def acquire_lock(self, world_id: str, lock: dict) -> None:
        """Attempt to acquire the host lock for *world_id*.

        MUST be atomic: if a valid (non-expired) lock exists for another host,
        raise ``LockConflictError`` without writing anything.

        Parameters
        ----------
        world_id:
            The world to lock.
        lock:
            The lock record to write (see module docstring for schema).

        Raises:
            LockConflictError: If another host holds a valid, non-expired lock.
            StorageUnavailableError: If the backend cannot be reached.
        """
        ...

    @abstractmethod
    def release_lock(self, world_id: str, session_id: str) -> None:
        """Release the host lock for *world_id* if it matches *session_id*.

        Raises:
            LockNotOwnedError: If the current lock belongs to a different session.
            StorageUnavailableError: If the backend cannot be reached.
        """
        ...

    @abstractmethod
    def refresh_lock(self, world_id: str, session_id: str, new_lock: dict) -> None:
        """Extend the TTL of an existing lock owned by *session_id*.

        Raises:
            LockNotOwnedError: If the current lock belongs to a different session.
            StorageUnavailableError: If the backend cannot be reached.
        """
        ...
