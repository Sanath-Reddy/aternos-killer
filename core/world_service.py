"""
core/world_service.py — Public world information API for Developer 2.

Exposes read-only world state: local manifest, remote manifest, and version
comparison.  The UI must NEVER manipulate world directories or manifests
directly.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from storage.provider import StorageProvider, StorageUnavailableError
from world.manager import WorldManager
from world.manifest import MalformedManifestError, WorldManifest

logger = logging.getLogger(__name__)


class WorldService:
    """Read-only world state surface for the UI layer.

    Parameters
    ----------
    world_manager:
        The underlying ``WorldManager`` instance.
    provider:
        Storage provider (used to fetch the remote manifest).
    """

    def __init__(self, world_manager: WorldManager, provider: StorageProvider) -> None:
        self._wm = world_manager
        self._provider = provider

    # ── Local manifest ─────────────────────────────────────────────────────────

    def get_local_manifest(self) -> Optional[Dict[str, Any]]:
        """Return the local committed manifest as a dict, or None.

        Example::

            {
                "world_id": "survival",
                "version": 184,
                "parent_version": 183,
                "snapshot": "snapshots/world-184.tar.zst",
                "sha256": "...",
                "minecraft_version": "1.21.4",
                "created_at": "...",
                "created_by": "alice-pc-..."
            }
        """
        try:
            m = self._wm.get_local_manifest()
            return m.to_dict() if m else None
        except MalformedManifestError as exc:
            logger.error("Malformed local manifest: %s", exc)
            return None

    # ── Remote manifest ────────────────────────────────────────────────────────

    def get_remote_manifest(self) -> Optional[Dict[str, Any]]:
        """Fetch the remote manifest from Drive and return as a dict, or None.

        Returns ``None`` if Drive has no manifest yet or is unreachable.
        The UI should show an appropriate message in each case.
        """
        try:
            raw = self._provider.get_manifest()
            if raw is None:
                return None
            WorldManifest.from_dict(raw)  # validate before returning
            return raw
        except StorageUnavailableError as exc:
            logger.error("Drive unavailable: %s", exc)
            return None
        except MalformedManifestError as exc:
            logger.error("Remote manifest is malformed: %s", exc)
            return None

    # ── Version comparison ─────────────────────────────────────────────────────

    def compare_versions(self) -> Dict[str, Any]:
        """Compare local vs remote manifest.

        Returns a dict::

            {
                "result": "UP_TO_DATE",   # or NEEDS_UPDATE / CONFLICT / LOCAL_AHEAD / NO_LOCAL
                "local_version":  184,    # None if no local
                "remote_version": 184,    # None if no remote
            }
        """
        try:
            remote_raw = self._provider.get_manifest()
            remote = WorldManifest.from_dict(remote_raw) if remote_raw else None
        except Exception as exc:
            logger.error("Failed to fetch remote manifest: %s", exc)
            remote = None

        compare = self._wm.compare_with_remote(remote)
        local = self._wm.get_local_manifest()

        return {
            "result": compare,
            "local_version":  local.version  if local  else None,
            "remote_version": remote.version if remote else None,
        }

    def validate_local_world(self) -> bool:
        """Return True if the local world directory exists and contains level.dat."""
        return self._wm.validate_local_world()
