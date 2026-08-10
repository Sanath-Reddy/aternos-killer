"""
session/session.py — Session orchestrator.

Ties together:
- SessionFSM (state machine)
- LockManager (host lock)
- WorldManager (world sync)
- MinecraftManager (process)
- StorageProvider (Drive)

The full host lifecycle::

    begin_host()
        → acquire lock
        → fetch remote manifest
        → compare local vs remote
        → download if NEEDS_UPDATE / NO_LOCAL
        → STARTING: start MC, wait for ready
        → ACTIVE

    end_host()
        → SAVING: save-all flush, confirm
        → stop MC, verify exit
        → SNAPSHOTTING: create snapshot, hash
        → UPLOADING: upload, update manifest
        → release lock
        → CLOSED

Error handling rules (per spec):
- download fails       → do NOT start MC
- snapshot fails       → do NOT update manifest
- upload fails         → do NOT update manifest, keep local snapshot
- manifest update fails→ keep local snapshot
- MC crashes           → FSM → ERROR, Drive state preserved
- conflict detected    → raise, never auto-resolve
- local ahead of Drive → raise, never overwrite
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from config.settings import BlockSyncConfig
from minecraft.manager import MinecraftManager, ProcessStatus
from session.lock import HostLock, LockManager
from session.state import InvalidTransitionError, SessionFSM, SessionState
from storage.provider import (
    DownloadError,
    LockConflictError,
    StorageProvider,
    StorageUnavailableError,
    UploadError,
)
from world.manager import (
    LocalWorldAheadError,
    WorldConflictError,
    WorldDownloadError,
    WorldManager,
)
from world.manifest import CompareResult, WorldManifest
from world.snapshot import SnapshotResult

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Session errors
# ──────────────────────────────────────────────────────────────────────────────

class SessionError(RuntimeError):
    """Wraps session-level failures with context."""


# ──────────────────────────────────────────────────────────────────────────────
# Session
# ──────────────────────────────────────────────────────────────────────────────

class Session:
    """Orchestrates the full BlockSync host session lifecycle.

    Parameters
    ----------
    config:
        Application configuration.
    provider:
        Storage backend (injected; never instantiated here).
    world_manager:
        WorldManager instance.
    minecraft_manager:
        MinecraftManager instance.
    lock_manager:
        LockManager instance.
    """

    def __init__(
        self,
        config: BlockSyncConfig,
        provider: StorageProvider,
        world_manager: WorldManager,
        minecraft_manager: MinecraftManager,
        lock_manager: LockManager,
    ) -> None:
        self._config    = config
        self._provider  = provider
        self._wm        = world_manager
        self._mc        = minecraft_manager
        self._lm        = lock_manager

        self._fsm       = SessionFSM()
        self._lock: Optional[HostLock] = None
        self._last_snapshot: Optional[SnapshotResult] = None
        self._last_manifest: Optional[WorldManifest] = None

        # Thread lock protecting lock/snapshot/manifest fields.
        self._state_lock = threading.Lock()

        # Watch MC crashes and push session to ERROR.
        self._mc_crash_observer_started = False

    # ── Public API ─────────────────────────────────────────────────────────────

    def begin_host(self) -> None:
        """Acquire the host role, sync the world, and start Minecraft.

        On any failure, the FSM transitions to ERROR and the exception is
        re-raised.  The active world on disk is never destroyed.

        Raises:
            LockConflictError: If another host holds the lock.
            WorldConflictError: If local and remote histories diverged.
            LocalWorldAheadError: If local is newer than Drive (upload incomplete?).
            WorldDownloadError: If the snapshot download/extraction fails.
            SessionError: On Minecraft start/ready timeout.
        """
        try:
            self._fsm.transition(SessionState.STARTING)
        except InvalidTransitionError as exc:
            raise SessionError(
                f"Cannot begin_host from state {self._fsm.state.value!r}"
            ) from exc

        try:
            # 1. Acquire lock.
            logger.info("=== BEGIN HOST ===")
            lock = self._lm.acquire()
            with self._state_lock:
                self._lock = lock

            # 2. Fetch remote manifest.
            remote_raw = self._provider.get_manifest()
            remote = WorldManifest.from_dict(remote_raw) if remote_raw else None

            # 3. Compare versions.
            compare = self._wm.compare_with_remote(remote)
            logger.info("World compare result: %s", compare)

            if compare == CompareResult.CONFLICT:
                raise WorldConflictError(
                    "Local and remote world histories have diverged. "
                    "Manual resolution required. "
                    "Do NOT host until this is resolved."
                )

            if compare == CompareResult.LOCAL_AHEAD:
                raise LocalWorldAheadError(
                    "Local world is ahead of Google Drive. "
                    "A previous upload may have been interrupted. "
                    "Check snapshots and re-upload manually if needed."
                )

            # 4. Download if needed.
            if compare in (CompareResult.NEEDS_UPDATE, CompareResult.NO_LOCAL):
                if remote is None:
                    raise SessionError(
                        "Drive has no manifest but local also has none. "
                        "Cannot start — no world to download."
                    )
                self._download_world(remote)

            # 5. Start Minecraft.
            self._mc.start()

            logger.info("Waiting for Minecraft to become ready …")
            became_ready = self._mc.wait_until_ready(
                timeout=self._config.ready_timeout
            )
            if not became_ready:
                raise SessionError(
                    "Minecraft process exited before becoming ready."
                )

            # 6. Register crash observer.
            self._start_crash_observer()

            self._fsm.transition(SessionState.ACTIVE)
            logger.info("=== SESSION ACTIVE — players may now connect ===")

        except Exception as exc:
            logger.error("begin_host failed: %s", exc, exc_info=True)
            self._fsm.force_error(reason=str(exc))
            self._safe_release_lock()
            raise

    def end_host(self) -> None:
        """Save, snapshot, upload, and release the host role.

        Failures at each step are logged and re-raised.  The local world and
        snapshot are preserved on partial failures.

        Raises:
            SessionError: On unexpected state or critical failures.
        """
        logger.info("=== END HOST — beginning shutdown sequence ===")

        # ── SAVING ────────────────────────────────────────────────────────────
        try:
            self._fsm.transition(SessionState.SAVING)
        except InvalidTransitionError as exc:
            raise SessionError(
                f"Cannot end_host from state {self._fsm.state.value!r}"
            ) from exc

        try:
            logger.info("Saving world …")
            self._mc.save(timeout=self._config.save_timeout)
        except Exception as exc:
            logger.error("Save failed: %s", exc)
            self._fsm.force_error(str(exc))
            raise SessionError(f"Save failed: {exc}") from exc

        # ── SNAPSHOTTING ──────────────────────────────────────────────────────
        self._fsm.transition(SessionState.SNAPSHOTTING)

        # Stop Minecraft BEFORE creating the snapshot.
        logger.info("Stopping Minecraft …")
        clean_stop = self._mc.stop(timeout=self._config.stop_timeout)
        if not clean_stop:
            logger.warning(
                "Minecraft did not exit cleanly; continuing with snapshot anyway."
            )

        # Determine next version number.
        local_manifest = self._wm.get_local_manifest()
        next_version = (local_manifest.version + 1) if local_manifest else 1

        try:
            logger.info("Creating snapshot v%s …", next_version)
            snapshot = self._wm.create_snapshot(version=next_version)
            with self._state_lock:
                self._last_snapshot = snapshot
            logger.info(
                "Snapshot ready: %s (sha256=%s…)",
                snapshot.path.name,
                snapshot.sha256[:12],
            )
        except Exception as exc:
            logger.error("Snapshot creation failed: %s", exc)
            self._fsm.force_error(str(exc))
            self._safe_release_lock()
            # DO NOT update manifest.
            raise SessionError(f"Snapshot creation failed: {exc}") from exc

        # ── UPLOADING ─────────────────────────────────────────────────────────
        self._fsm.transition(SessionState.UPLOADING)

        try:
            logger.info("Uploading snapshot …")
            remote_name = snapshot.path.name  # e.g. "world-185.tar.zst"
            self._provider.upload_snapshot(snapshot.path, remote_name)
        except (UploadError, StorageUnavailableError) as exc:
            logger.error(
                "Upload failed: %s — local snapshot preserved at %s",
                exc, snapshot.path,
            )
            self._fsm.force_error(str(exc))
            self._safe_release_lock()
            # DO NOT update manifest.
            raise SessionError(f"Upload failed: {exc}") from exc

        # Build and commit new manifest.
        try:
            if local_manifest is None:
                # First-ever commit.
                new_manifest = WorldManifest(
                    world_id=self._config.world_id,
                    version=next_version,
                    parent_version=next_version - 1,
                    snapshot=f"snapshots/{remote_name}",
                    sha256=snapshot.sha256,
                    minecraft_version=self._config.minecraft_version,
                    created_at=__import__("datetime").datetime.now(
                        tz=__import__("datetime").timezone.utc
                    ),
                    created_by=self._config.host_id,
                )
            else:
                new_manifest = local_manifest.make_next(
                    snapshot=f"snapshots/{remote_name}",
                    sha256=snapshot.sha256,
                    created_by=self._config.host_id,
                    minecraft_version=self._config.minecraft_version,
                )

            logger.info("Updating manifest → v%s …", new_manifest.version)
            self._provider.update_manifest(new_manifest.to_dict())
            self._wm.save_local_manifest(new_manifest)
            with self._state_lock:
                self._last_manifest = new_manifest

            logger.info("Manifest committed: %s", new_manifest)
        except Exception as exc:
            logger.error(
                "Manifest update failed: %s — local snapshot preserved at %s",
                exc, snapshot.path,
            )
            self._fsm.force_error(str(exc))
            self._safe_release_lock()
            # DO NOT delete local snapshot — kept for retry.
            raise SessionError(f"Manifest update failed: {exc}") from exc

        # ── CLOSED ────────────────────────────────────────────────────────────
        self._safe_release_lock()
        self._fsm.transition(SessionState.CLOSED)
        logger.info("=== SESSION CLOSED — world v%s committed ===", new_manifest.version)

    # ── State queries (for Developer 2's service layer) ────────────────────────

    def get_state(self) -> SessionState:
        """Return current FSM state."""
        return self._fsm.state

    def get_lock(self) -> Optional[HostLock]:
        with self._state_lock:
            return self._lock

    def get_last_snapshot(self) -> Optional[SnapshotResult]:
        with self._state_lock:
            return self._last_snapshot

    def get_last_manifest(self) -> Optional[WorldManifest]:
        with self._state_lock:
            return self._last_manifest

    def add_state_observer(self, callback) -> None:
        """Register a callback for FSM state changes.

        Signature: ``callback(old_state: SessionState, new_state: SessionState)``
        """
        self._fsm.add_observer(callback)

    def reset_error(self) -> None:
        """Transition from ERROR → CLOSED to allow retrying begin_host."""
        self._fsm.transition(SessionState.CLOSED)

    # ── Private ────────────────────────────────────────────────────────────────

    def _download_world(self, remote: WorldManifest) -> None:
        """Download and apply the remote snapshot."""
        remote_name = remote.snapshot.split("/")[-1]  # "world-184.tar.zst"
        dest = self._config.snapshots_dir / remote_name

        logger.info("Downloading snapshot %s …", remote_name)
        try:
            self._provider.download_snapshot(
                remote_name=remote_name,
                dest=dest,
                expected_sha256=remote.sha256,
            )
        except (DownloadError, StorageUnavailableError) as exc:
            raise SessionError(f"World download failed: {exc}") from exc

        self._wm.apply_download(archive_path=dest, remote_manifest=remote)

    def _safe_release_lock(self) -> None:
        """Release the lock without raising (best-effort cleanup)."""
        with self._state_lock:
            lock = self._lock
            self._lock = None

        if lock is None:
            return
        try:
            self._lm.release(lock)
        except Exception as exc:
            logger.error(
                "Failed to release lock during cleanup: %s — "
                "lock will expire naturally at %s",
                exc, lock.expires_at.isoformat(),
            )

    def _start_crash_observer(self) -> None:
        """Watch for MC crashes and push the FSM to ERROR."""
        if self._mc_crash_observer_started:
            return
        self._mc_crash_observer_started = True

        def _watcher():
            import time
            while True:
                time.sleep(2)
                status = self._mc.status
                fsm_state = self._fsm.state
                if (
                    status == ProcessStatus.CRASHED
                    and fsm_state not in (
                        SessionState.CLOSED,
                        SessionState.ERROR,
                        SessionState.SNAPSHOTTING,
                        SessionState.UPLOADING,
                    )
                ):
                    logger.error(
                        "MC crash detected while session is %s — forcing ERROR",
                        fsm_state.value,
                    )
                    self._fsm.force_error("Minecraft process crashed unexpectedly")
                    break
                if fsm_state in (SessionState.CLOSED, SessionState.ERROR):
                    break  # session ended; stop watching

        t = threading.Thread(target=_watcher, daemon=True, name="mc-crash-watcher")
        t.start()
