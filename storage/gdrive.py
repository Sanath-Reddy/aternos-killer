"""
storage/gdrive.py — Google Drive implementation of StorageProvider.

Authentication: Google Service Account (JSON key file).
The key file path is read from ``BlockSyncConfig.credentials_file`` at
runtime and NEVER embedded in source.

Drive folder layout (inside the shared folder)::

    <gdrive_folder_id>/
    ├── manifest.json          ← current world manifest
    ├── lock.json              ← host session lock
    └── snapshots/
        ├── world-183.tar.zst
        ├── world-184.tar.zst
        └── world-185.tar.zst

Lock atomicity
--------------
Google Drive does not provide true compare-and-swap, but for a small trusted
friend group we implement optimistic locking:

1. ``get_lock()`` — reads the current lock file.
2. If it exists and is not expired for another host → ``LockConflictError``.
3. Otherwise upload a new lock file.

This is sufficient for a trusted group.  A stricter backend can replace this
implementation behind the ``StorageProvider`` interface.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

from storage.provider import (
    DownloadError,
    LockConflictError,
    LockNotOwnedError,
    SnapshotNotFoundError,
    StorageError,
    StorageProvider,
    StorageUnavailableError,
    UploadError,
)

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/drive"]
_MANIFEST_FILENAME = "manifest.json"
_LOCK_FILENAME     = "lock.json"
_SNAPSHOTS_FOLDER  = "snapshots"
_BUFFER_SIZE       = 65_536   # 64 KiB download buffer
_MIME_JSON         = "application/json"
_MIME_OCTET        = "application/octet-stream"

# Resumable upload threshold: use resumable for files > 5 MB
_RESUMABLE_THRESHOLD = 5 * 1024 * 1024


# ──────────────────────────────────────────────────────────────────────────────
# GoogleDriveStorageProvider
# ──────────────────────────────────────────────────────────────────────────────

class GoogleDriveStorageProvider(StorageProvider):
    """Google Drive implementation of ``StorageProvider``.

    Parameters
    ----------
    folder_id:
        ID of the shared Google Drive folder.
    credentials_file:
        Absolute path to the service account JSON key file.
    """

    def __init__(self, folder_id: str, credentials_file: Path) -> None:
        self._folder_id = folder_id
        self._credentials_file = credentials_file
        self._service = None           # lazy init
        self._snapshots_folder_id: Optional[str] = None

    # ── Authentication (lazy) ─────────────────────────────────────────────────

    def _get_service(self):
        """Return (and cache) the authenticated Drive service client."""
        if self._service is not None:
            return self._service
        try:
            creds = service_account.Credentials.from_service_account_file(
                str(self._credentials_file), scopes=_SCOPES
            )
            self._service = build("drive", "v3", credentials=creds, cache_discovery=False)
            logger.info("Google Drive service authenticated (service account)")
        except FileNotFoundError as exc:
            raise StorageUnavailableError(
                f"Service account file not found: {self._credentials_file}"
            ) from exc
        except Exception as exc:
            raise StorageUnavailableError(
                f"Failed to authenticate with Google Drive: {exc}"
            ) from exc
        return self._service

    # ── Retry helper ──────────────────────────────────────────────────────────

    def _with_retry(self, action, retries: int = 3, delay: float = 0.5):
        """Execute action, retrying on transient socket / SSL errors."""
        last_exc = None
        for attempt in range(retries):
            try:
                return action()
            except (HttpError, StorageError):
                raise
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "Drive API network/SSL glitch (attempt %d/%d): %s",
                    attempt + 1, retries, exc,
                )
                self._service = None  # reset service to open fresh connection
                time.sleep(delay * (attempt + 1))
        raise StorageUnavailableError(f"Drive network error: {last_exc}") from last_exc

    # ── Manifest ──────────────────────────────────────────────────────────────

    def get_manifest(self) -> Optional[dict]:
        """Fetch ``manifest.json`` from Drive."""
        def _fetch():
            file_id = self._find_file(_MANIFEST_FILENAME, self._folder_id)
            if file_id is None:
                return None
            content = self._download_as_bytes(file_id)
            return json.loads(content.decode("utf-8"))

        try:
            return self._with_retry(_fetch)
        except StorageError:
            raise
        except Exception as exc:
            raise StorageUnavailableError(f"Failed to fetch manifest: {exc}") from exc

    def update_manifest(self, manifest: dict) -> None:
        """Upload or replace ``manifest.json`` on Drive."""
        payload = json.dumps(manifest, indent=2).encode("utf-8")
        try:
            file_id = self._find_file(_MANIFEST_FILENAME, self._folder_id)
            if file_id is None:
                self._upload_bytes(
                    _MANIFEST_FILENAME, payload, _MIME_JSON, self._folder_id
                )
                logger.info("manifest.json created on Drive")
            else:
                self._update_bytes(file_id, payload, _MIME_JSON)
                logger.info("manifest.json updated on Drive")
        except StorageError:
            raise
        except HttpError as exc:
            raise StorageError(f"Failed to update manifest: {exc}") from exc

    # ── Snapshots ─────────────────────────────────────────────────────────────

    def upload_snapshot(self, local_path: Path, remote_name: str) -> str:
        """Upload *local_path* to the ``snapshots/`` sub-folder on Drive.

        Returns the Drive file ID of the uploaded snapshot.
        """
        if not local_path.exists():
            raise UploadError(f"Local snapshot not found: {local_path}")

        snapshots_folder_id = self._get_or_create_snapshots_folder()
        size = local_path.stat().st_size

        logger.info(
            "Uploading snapshot %s (%.1f MB) …", remote_name, size / 1_048_576
        )
        try:
            file_id = self._find_file(remote_name, snapshots_folder_id)

            media = MediaFileUpload(
                str(local_path),
                mimetype=_MIME_OCTET,
                resumable=(size > _RESUMABLE_THRESHOLD),
                chunksize=10 * 1024 * 1024,  # 10 MB chunks
            )
            svc = self._get_service()

            if file_id is None:
                meta = {
                    "name": remote_name,
                    "parents": [snapshots_folder_id],
                }
                result = svc.files().create(
                    body=meta, media_body=media, fields="id"
                ).execute()
                file_id = result["id"]
            else:
                result = svc.files().update(
                    fileId=file_id, media_body=media, fields="id"
                ).execute()
                file_id = result["id"]

            logger.info("Snapshot uploaded: %s (file_id=%s)", remote_name, file_id)
            return file_id

        except StorageError:
            raise
        except HttpError as exc:
            raise UploadError(f"Failed to upload {remote_name}: {exc}") from exc

    def download_snapshot(
        self,
        remote_name: str,
        dest: Path,
        expected_sha256: str,
    ) -> None:
        """Download *remote_name* from ``snapshots/`` folder to *dest*.

        Verifies SHA-256 after download.
        """
        snapshots_folder_id = self._get_or_create_snapshots_folder()
        file_id = self._find_file(remote_name, snapshots_folder_id)
        if file_id is None:
            raise SnapshotNotFoundError(f"Snapshot not found on Drive: {remote_name}")

        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp_dest = dest.parent / (dest.name + ".downloading")

        logger.info("Downloading snapshot %s …", remote_name)
        try:
            svc = self._get_service()
            request = svc.files().get_media(fileId=file_id)

            with tmp_dest.open("wb") as fh:
                downloader = MediaIoBaseDownload(fh, request, chunksize=10 * 1024 * 1024)
                done = False
                while not done:
                    status, done = downloader.next_chunk()
                    if status:
                        pct = int(status.progress() * 100)
                        logger.debug("Download progress: %d%%", pct)

            # Verify hash.
            actual = _sha256_file(tmp_dest)
            if actual != expected_sha256.lower():
                tmp_dest.unlink(missing_ok=True)
                raise DownloadError(
                    f"SHA-256 mismatch for {remote_name}:\n"
                    f"  expected: {expected_sha256.lower()}\n"
                    f"  actual:   {actual}"
                )

            tmp_dest.replace(dest)
            logger.info("Snapshot downloaded and verified: %s", remote_name)

        except StorageError:
            raise
        except HttpError as exc:
            tmp_dest.unlink(missing_ok=True)
            raise DownloadError(f"Drive download failed: {exc}") from exc
        except Exception as exc:
            tmp_dest.unlink(missing_ok=True)
            raise DownloadError(f"Unexpected download error: {exc}") from exc

    # ── Host Lock ─────────────────────────────────────────────────────────────

    def get_lock(self, world_id: str) -> Optional[dict]:
        """Fetch ``lock.json`` from Drive."""
        def _fetch():
            file_id = self._find_file(_LOCK_FILENAME, self._folder_id)
            if file_id is None:
                return None
            content = self._download_as_bytes(file_id)
            lock = json.loads(content.decode("utf-8"))
            if lock.get("world_id") != world_id:
                logger.warning(
                    "Lock world_id mismatch: expected %r got %r",
                    world_id, lock.get("world_id"),
                )
                return None
            return lock

        try:
            return self._with_retry(_fetch)
        except StorageError:
            raise
        except Exception as exc:
            raise StorageUnavailableError(f"Failed to read lock: {exc}") from exc

    def acquire_lock(self, world_id: str, lock: dict) -> None:
        """Write *lock* as the active lock if none exists or the existing is expired.

        Raises ``LockConflictError`` if a valid lock exists for another host.
        """
        existing = self.get_lock(world_id)
        if existing is not None:
            expires_raw = existing.get("expires_at")
            try:
                expires = datetime.fromisoformat(expires_raw)
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                expires = datetime.min.replace(tzinfo=timezone.utc)

            now = datetime.now(tz=timezone.utc)
            if expires > now:
                # Lock is still valid — check if it's ours.
                if existing.get("session_id") != lock.get("session_id"):
                    raise LockConflictError(existing)
                # It's ours; refresh in place.
                logger.debug("Lock already held by us; refreshing.")

        payload = json.dumps(lock, indent=2).encode("utf-8")
        try:
            file_id = self._find_file(_LOCK_FILENAME, self._folder_id)
            if file_id is None:
                self._upload_bytes(_LOCK_FILENAME, payload, _MIME_JSON, self._folder_id)
            else:
                self._update_bytes(file_id, payload, _MIME_JSON)
            logger.info("Host lock acquired (session=%s)", lock.get("session_id", "?"))
        except StorageError:
            raise
        except HttpError as exc:
            raise StorageError(f"Failed to acquire lock: {exc}") from exc

    def release_lock(self, world_id: str, session_id: str) -> None:
        """Delete the lock file if it matches *session_id*."""
        existing = self.get_lock(world_id)
        if existing is None:
            logger.warning("release_lock called but no lock exists on Drive")
            return
        if existing.get("session_id") != session_id:
            raise LockNotOwnedError(
                f"Cannot release lock owned by session {existing.get('session_id')!r}"
            )
        try:
            file_id = self._find_file(_LOCK_FILENAME, self._folder_id)
            if file_id:
                self._get_service().files().delete(fileId=file_id).execute()
            logger.info("Host lock released (session=%s)", session_id)
        except HttpError as exc:
            raise StorageError(f"Failed to release lock: {exc}") from exc

    def refresh_lock(self, world_id: str, session_id: str, new_lock: dict) -> None:
        """Replace the lock document with *new_lock* if session IDs match."""
        existing = self.get_lock(world_id)
        if existing is None:
            raise LockNotOwnedError("Cannot refresh: no lock exists")
        if existing.get("session_id") != session_id:
            raise LockNotOwnedError(
                f"Cannot refresh lock owned by {existing.get('session_id')!r}"
            )
        payload = json.dumps(new_lock, indent=2).encode("utf-8")
        try:
            file_id = self._find_file(_LOCK_FILENAME, self._folder_id)
            if file_id:
                self._update_bytes(file_id, payload, _MIME_JSON)
            else:
                self._upload_bytes(_LOCK_FILENAME, payload, _MIME_JSON, self._folder_id)
            logger.debug("Host lock refreshed (session=%s)", session_id)
        except HttpError as exc:
            raise StorageError(f"Failed to refresh lock: {exc}") from exc

    # ── Drive helpers ─────────────────────────────────────────────────────────

    def _find_file(self, name: str, parent_id: str) -> Optional[str]:
        """Return the Drive file ID of *name* in *parent_id*, or None."""
        def _call():
            svc = self._get_service()
            q = (
                f"name = {json.dumps(name)} "
                f"and '{parent_id}' in parents "
                f"and trashed = false"
            )
            result = svc.files().list(q=q, fields="files(id)", pageSize=2).execute()
            files = result.get("files", [])
            if not files:
                return None
            if len(files) > 1:
                logger.warning(
                    "Multiple files named %r in folder %r; using first", name, parent_id
                )
            return files[0]["id"]

        return self._with_retry(_call)

    def _download_as_bytes(self, file_id: str) -> bytes:
        def _call():
            svc = self._get_service()
            request = svc.files().get_media(fileId=file_id)
            buf = io.BytesIO()
            downloader = MediaIoBaseDownload(buf, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            return buf.getvalue()

        return self._with_retry(_call)

    def _upload_bytes(
        self, name: str, data: bytes, mime: str, parent_id: str
    ) -> str:
        def _call():
            svc = self._get_service()
            from googleapiclient.http import MediaIoBaseUpload
            media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime)
            meta = {"name": name, "parents": [parent_id]}
            result = svc.files().create(body=meta, media_body=media, fields="id").execute()
            return result["id"]

        return self._with_retry(_call)

    def _update_bytes(self, file_id: str, data: bytes, mime: str) -> None:
        def _call():
            from googleapiclient.http import MediaIoBaseUpload
            svc = self._get_service()
            media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime)
            svc.files().update(fileId=file_id, media_body=media).execute()

        return self._with_retry(_call)

    def _get_or_create_snapshots_folder(self) -> str:
        """Return (and cache) the Drive folder ID for ``snapshots/``."""
        if self._snapshots_folder_id is not None:
            return self._snapshots_folder_id

        folder_id = self._find_file(_SNAPSHOTS_FOLDER, self._folder_id)
        if folder_id is None:
            logger.info("Creating 'snapshots' subfolder on Drive")
            svc = self._get_service()
            meta = {
                "name": _SNAPSHOTS_FOLDER,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [self._folder_id],
            }
            result = svc.files().create(body=meta, fields="id").execute()
            folder_id = result["id"]

        self._snapshots_folder_id = folder_id
        return folder_id


# ──────────────────────────────────────────────────────────────────────────────
# Utilities
# ──────────────────────────────────────────────────────────────────────────────

def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(65_536):
            h.update(chunk)
    return h.hexdigest()
