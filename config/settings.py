"""
config/settings.py — BlockSync application configuration.

All runtime configuration lives here. Credentials are referenced by *path*,
never embedded. The credentials file itself is excluded from version control
via .gitignore.
"""

from __future__ import annotations

import logging
import platform
import socket
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Defaults
# ──────────────────────────────────────────────────────────────────────────────

_DEFAULT_JVM_ARGS: List[str] = ["-Xmx4G", "-Xms1G"]
_DEFAULT_LOCK_TTL: int = 3600          # 1 hour
_DEFAULT_READY_TIMEOUT: float = 180.0  # seconds to wait for "Done" line
_DEFAULT_STOP_TIMEOUT: float = 60.0    # seconds to wait for graceful stop
_DEFAULT_SAVE_TIMEOUT: float = 30.0    # seconds to wait for save-all flush


def _default_host_id() -> str:
    """Generate a stable, human-readable machine identifier.

    Uses ``hostname-<short-uuid>`` format. The UUID is derived from the
    MAC address so it stays consistent across restarts on the same machine.
    """
    hostname = socket.gethostname().lower().replace(" ", "-")
    node_uuid = str(uuid.uuid1()).split("-")[0]  # time-low segment, stable per boot
    return f"{hostname}-{node_uuid}"


# ──────────────────────────────────────────────────────────────────────────────
# BlockSyncConfig
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class BlockSyncConfig:
    """Central configuration for the BlockSync backend.

    Example usage::

        cfg = BlockSyncConfig(
            world_id="survival",
            world_dir=Path("C:/mc-server/world"),
            server_dir=Path("C:/mc-server"),
            gdrive_folder_id="1ABC...xyz",
            credentials_file=Path("C:/secrets/service_account.json"),
        )

    Required fields have no default.  Optional fields have sensible defaults.
    """

    # ── Required ──────────────────────────────────────────────────────────────

    world_id: str
    """Logical identifier for this world (e.g. ``"survival"``).
    Used as a key in the manifest and lock."""

    world_dir: Path
    """User-specified path to the Minecraft world folder
    (e.g. ``C:/mc-server/world``). This is the *active* world directory."""

    server_dir: Path
    """Directory that contains ``server.jar`` and ``server.properties``."""

    gdrive_folder_id: str
    """Google Drive folder ID (from the shared folder URL) where snapshots
    and the manifest are stored."""

    credentials_file: Path
    """Absolute path to the Google service account JSON key file.
    NEVER committed to version control."""

    # ── Optional ──────────────────────────────────────────────────────────────

    host_id: str = field(default_factory=_default_host_id)
    """Unique identifier for this machine.  Auto-generated from hostname + MAC
    if not supplied."""

    minecraft_version: str = "1.21.4"
    """Target Minecraft version string. Used when auto-downloading the server
    JAR via the Mojang version manifest API."""

    java_path: str = "java"
    """Path to the Java executable. ``"java"`` resolves via PATH."""

    jvm_args: List[str] = field(default_factory=lambda: list(_DEFAULT_JVM_ARGS))
    """JVM heap and GC flags passed before ``-jar``."""

    lock_ttl_seconds: int = _DEFAULT_LOCK_TTL
    """Seconds before an unrenewed host lock is considered stale."""

    ready_timeout: float = _DEFAULT_READY_TIMEOUT
    """Seconds to wait for the ``Done (...)`` ready signal after ``start()``."""

    stop_timeout: float = _DEFAULT_STOP_TIMEOUT
    """Seconds to wait for the Minecraft process to exit after ``stop()``."""

    save_timeout: float = _DEFAULT_SAVE_TIMEOUT
    """Seconds to wait for ``save-all flush`` confirmation."""

    # ── Derived paths (computed from server_dir) ───────────────────────────────

    @property
    def server_jar(self) -> Path:
        """Absolute path to ``server.jar`` inside ``server_dir``."""
        return self.server_dir / "server.jar"

    @property
    def work_dir(self) -> Path:
        """Scratch directory for safe world-swap operations.
        Lives next to ``world_dir`` to keep renames on the same filesystem."""
        return self.world_dir.parent / ".blocksync_work"

    @property
    def world_new_dir(self) -> Path:
        """Incoming world is extracted here before being moved to ``world_dir``."""
        return self.work_dir / "world.new"

    @property
    def world_backup_dir(self) -> Path:
        """Previous world is kept here while the new one is being validated."""
        return self.work_dir / "world.backup"

    @property
    def snapshots_dir(self) -> Path:
        """Local snapshot staging area."""
        return self.work_dir / "snapshots"

    # ── Validation ────────────────────────────────────────────────────────────

    def validate(self) -> None:
        """Raise ``ValueError`` if the configuration is obviously invalid.

        Does NOT check network reachability or Drive access.
        """
        if not self.world_id:
            raise ValueError("world_id must not be empty")
        if not self.gdrive_folder_id:
            raise ValueError("gdrive_folder_id must not be empty")
        if not self.credentials_file:
            raise ValueError("credentials_file must be specified")
        if not self.credentials_file.exists():
            raise ValueError(
                f"credentials_file does not exist: {self.credentials_file}"
            )
        if self.lock_ttl_seconds <= 0:
            raise ValueError("lock_ttl_seconds must be > 0")
        logger.debug("BlockSyncConfig validated OK (host_id=%s)", self.host_id)

    def ensure_work_dirs(self) -> None:
        """Create work directories if they do not exist."""
        for d in (self.work_dir, self.snapshots_dir):
            d.mkdir(parents=True, exist_ok=True)
        logger.debug("Work directories ensured: %s", self.work_dir)

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def __str__(self) -> str:
        return (
            f"BlockSyncConfig("
            f"world_id={self.world_id!r}, "
            f"host_id={self.host_id!r}, "
            f"minecraft_version={self.minecraft_version!r}, "
            f"world_dir={self.world_dir}, "
            f"server_dir={self.server_dir}"
            f")"
        )
