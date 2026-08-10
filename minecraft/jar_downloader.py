"""
minecraft/jar_downloader.py — Download the Minecraft server JAR via Mojang's API.

Mojang publishes a version manifest at:
    https://launchermeta.mojang.com/mc/game/version_manifest_v2.json

Each version entry contains a URL to its own version manifest, which in turn
contains a download URL for the server JAR (with SHA1 for verification).

Usage::

    downloader = JarDownloader(server_dir=Path("C:/mc-server"))
    jar_path = downloader.ensure_jar(version="1.21.4")
    # → C:/mc-server/server.jar

If the JAR already exists and passes SHA1 verification, the download is skipped.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_MANIFEST_URL = "https://launchermeta.mojang.com/mc/game/version_manifest_v2.json"
_TIMEOUT = 30          # seconds for HTTP requests
_CHUNK_SIZE = 65_536   # 64 KiB download buffer


# ──────────────────────────────────────────────────────────────────────────────
# Exceptions
# ──────────────────────────────────────────────────────────────────────────────

class JarDownloadError(RuntimeError):
    """Raised when the server JAR cannot be downloaded or verified."""


class UnknownVersionError(JarDownloadError):
    """Raised when the requested Minecraft version is not found in the manifest."""


# ──────────────────────────────────────────────────────────────────────────────
# JarDownloader
# ──────────────────────────────────────────────────────────────────────────────

class JarDownloader:
    """Download and verify the Minecraft server JAR from Mojang's CDN.

    Parameters
    ----------
    server_dir:
        Directory where ``server.jar`` will be saved.
    """

    def __init__(self, server_dir: Path) -> None:
        self._server_dir = server_dir

    # ── Public API ─────────────────────────────────────────────────────────────

    def ensure_jar(self, version: str) -> Path:
        """Ensure ``server.jar`` exists and is correct for *version*.

        If the file already exists and passes SHA1 verification (or is a custom JAR),
        the download is skipped. Otherwise it is downloaded.

        Parameters
        ----------
        version:
            Minecraft version string, e.g. ``"1.21.4"`` or ``"26.2"``.

        Returns:
            Absolute path to the verified ``server.jar``.

        Raises:
            UnknownVersionError: If the version is not in Mojang's manifest and no local JAR exists.
            JarDownloadError: On network or verification failure.
        """
        jar_path = self._server_dir / "server.jar"
        self._server_dir.mkdir(parents=True, exist_ok=True)

        # Check existing file first.
        if jar_path.exists():
            try:
                version_info = self._get_version_info(version)
                server_download = version_info.get("downloads", {}).get("server")
                if server_download:
                    jar_sha1 = server_download["sha1"]
                    actual_sha1 = _sha1_file(jar_path)
                    if actual_sha1 == jar_sha1:
                        logger.info(
                            "server.jar already present and verified (%s). Skipping download.",
                            version,
                        )
                        return jar_path
                    else:
                        logger.warning(
                            "Existing server.jar SHA1 mismatch (expected %s, got %s). Re-downloading …",
                            jar_sha1, actual_sha1,
                        )
            except UnknownVersionError:
                logger.info(
                    "server.jar present locally for custom version %s. Skipping Mojang download.",
                    version,
                )
                return jar_path

        # Fetch version-specific metadata for download.
        logger.info("Fetching Mojang version manifest …")
        version_info = self._get_version_info(version)
        server_download = version_info.get("downloads", {}).get("server")

        if server_download is None:
            raise JarDownloadError(
                f"Minecraft version {version!r} does not have a server JAR available."
            )

        jar_url  = server_download["url"]
        jar_sha1 = server_download["sha1"]
        jar_size = server_download.get("size", 0)

        # Download.
        logger.info(
            "Downloading server JAR for Minecraft %s (%.1f MB) from %s …",
            version, jar_size / 1_048_576, jar_url,
        )
        tmp_path = jar_path.parent / "server.jar.tmp"
        try:
            self._download(jar_url, tmp_path)
        except Exception as exc:
            tmp_path.unlink(missing_ok=True)
            raise JarDownloadError(f"Download failed: {exc}") from exc

        # Verify.
        actual_sha1 = _sha1_file(tmp_path)
        if actual_sha1 != jar_sha1:
            tmp_path.unlink(missing_ok=True)
            raise JarDownloadError(
                f"SHA1 mismatch for downloaded server.jar\n"
                f"  expected: {jar_sha1}\n"
                f"  actual:   {actual_sha1}"
            )

        tmp_path.replace(jar_path)
        logger.info("server.jar downloaded and verified for Minecraft %s", version)
        return jar_path

    def list_available_versions(self, include_snapshots: bool = False):
        """Return a list of available Minecraft versions from Mojang's manifest.

        Parameters
        ----------
        include_snapshots:
            If True, include snapshot versions (e.g. ``"1.22-pre1"``).
            Defaults to False (release versions only).

        Returns:
            List of version ID strings, newest first.
        """
        data = self._fetch_json(_MANIFEST_URL)
        versions = data.get("versions", [])
        if not include_snapshots:
            versions = [v for v in versions if v.get("type") == "release"]
        return [v["id"] for v in versions]

    # ── Private ────────────────────────────────────────────────────────────────

    def _get_version_info(self, version: str) -> dict:
        """Fetch the per-version metadata JSON from Mojang."""
        manifest = self._fetch_json(_MANIFEST_URL)
        versions = manifest.get("versions", [])

        entry = next((v for v in versions if v["id"] == version), None)
        if entry is None:
            available = [v["id"] for v in versions if v.get("type") == "release"][:10]
            raise UnknownVersionError(
                f"Minecraft version {version!r} not found in Mojang manifest.\n"
                f"Recent releases: {available}"
            )

        version_manifest_url = entry["url"]
        return self._fetch_json(version_manifest_url)

    def _fetch_json(self, url: str) -> dict:
        try:
            resp = requests.get(url, timeout=_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            raise JarDownloadError(f"HTTP request failed: {url!r} — {exc}") from exc

    def _download(self, url: str, dest: Path) -> None:
        with requests.get(url, stream=True, timeout=_TIMEOUT) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            with dest.open("wb") as fh:
                for chunk in resp.iter_content(chunk_size=_CHUNK_SIZE):
                    if chunk:
                        fh.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            pct = int(downloaded / total * 100)
                            if pct % 10 == 0:
                                logger.debug("Download progress: %d%%", pct)


# ──────────────────────────────────────────────────────────────────────────────
# Utilities
# ──────────────────────────────────────────────────────────────────────────────

def _sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as fh:
        while chunk := fh.read(65_536):
            h.update(chunk)
    return h.hexdigest()
