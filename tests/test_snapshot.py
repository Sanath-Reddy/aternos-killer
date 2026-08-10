"""
tests/test_snapshot.py — Unit tests for SnapshotBuilder.

These tests create real files and directories in a temporary location.
No mocking — we want to verify that the actual tar.zst pipeline works.
"""

import hashlib
from pathlib import Path

import pytest
from world.snapshot import (
    SnapshotBuilder,
    SnapshotExtractionError,
    SnapshotVerificationError,
)


@pytest.fixture
def tmp_world(tmp_path: Path) -> Path:
    """Create a minimal fake Minecraft world directory."""
    world = tmp_path / "world"
    world.mkdir()
    (world / "level.dat").write_bytes(b"\x1f\x8b fake level.dat data " * 50)
    (world / "region").mkdir()
    (world / "region" / "r.0.0.mca").write_bytes(b"\x00" * 4096)
    subdir = world / "playerdata"
    subdir.mkdir()
    (subdir / "player1.dat").write_bytes(b"player data" * 10)
    return world


@pytest.fixture
def builder() -> SnapshotBuilder:
    return SnapshotBuilder()


# ──────────────────────────────────────────────────────────────────────────────
# create()
# ──────────────────────────────────────────────────────────────────────────────

class TestCreate:
    def test_creates_archive(self, builder, tmp_world, tmp_path):
        dest = tmp_path / "snapshots"
        result = builder.create(tmp_world, dest, version=1)
        assert result.path.exists()
        assert result.path.name == "world-1.tar.zst"

    def test_returns_correct_sha256(self, builder, tmp_world, tmp_path):
        result = builder.create(tmp_world, tmp_path / "snaps", version=1)
        actual = builder.calculate_sha256(result.path)
        assert result.sha256 == actual

    def test_archive_size_nonzero(self, builder, tmp_world, tmp_path):
        result = builder.create(tmp_world, tmp_path / "snaps", version=1)
        assert result.size_bytes > 0

    def test_duration_recorded(self, builder, tmp_world, tmp_path):
        result = builder.create(tmp_world, tmp_path / "snaps", version=1)
        assert result.duration_s >= 0

    def test_missing_world_dir_raises(self, builder, tmp_path):
        with pytest.raises(Exception):
            builder.create(tmp_path / "nonexistent", tmp_path / "snaps", version=1)

    def test_dest_dir_created_if_missing(self, builder, tmp_world, tmp_path):
        dest = tmp_path / "deep" / "nested" / "snaps"
        result = builder.create(tmp_world, dest, version=5)
        assert result.path.exists()


# ──────────────────────────────────────────────────────────────────────────────
# verify()
# ──────────────────────────────────────────────────────────────────────────────

class TestVerify:
    def test_correct_hash_passes(self, builder, tmp_world, tmp_path):
        result = builder.create(tmp_world, tmp_path / "snaps", version=1)
        assert builder.verify(result.path, result.sha256) is True

    def test_wrong_hash_raises(self, builder, tmp_world, tmp_path):
        result = builder.create(tmp_world, tmp_path / "snaps", version=1)
        with pytest.raises(SnapshotVerificationError):
            builder.verify(result.path, "0" * 64)

    def test_missing_file_raises(self, builder, tmp_path):
        with pytest.raises(SnapshotVerificationError):
            builder.verify(tmp_path / "nonexistent.tar.zst", "a" * 64)


# ──────────────────────────────────────────────────────────────────────────────
# extract() — roundtrip
# ──────────────────────────────────────────────────────────────────────────────

class TestExtract:
    def test_roundtrip(self, builder, tmp_world, tmp_path):
        """Create a snapshot then extract it and compare file contents."""
        snaps_dir  = tmp_path / "snaps"
        extract_to = tmp_path / "restored"

        result = builder.create(tmp_world, snaps_dir, version=1)
        builder.extract(result.path, extract_to)

        # The extracted directory should exist and contain the world contents.
        # tarfile.add uses arcname=world.name → top-level dir named "world".
        extracted_world = extract_to / "world"
        assert extracted_world.exists(), f"Expected {extracted_world} to exist"
        assert (extracted_world / "level.dat").exists()
        assert (extracted_world / "region" / "r.0.0.mca").exists()

    def test_extract_content_matches(self, builder, tmp_world, tmp_path):
        snaps_dir  = tmp_path / "snaps"
        extract_to = tmp_path / "restored"

        result = builder.create(tmp_world, snaps_dir, version=1)
        original_data = (tmp_world / "level.dat").read_bytes()

        builder.extract(result.path, extract_to)
        restored_data = (extract_to / "world" / "level.dat").read_bytes()
        assert original_data == restored_data

    def test_stale_tmp_dir_is_cleaned_before_extract(self, builder, tmp_world, tmp_path):
        snaps_dir  = tmp_path / "snaps"
        extract_to = tmp_path / "restored"
        stale_tmp  = extract_to.parent / (extract_to.name + ".tmp")

        # Create a stale .tmp dir (simulating a previous failed extraction).
        stale_tmp.mkdir(parents=True)
        (stale_tmp / "stale_file.txt").write_text("leftover")

        result = builder.create(tmp_world, snaps_dir, version=1)
        builder.extract(result.path, extract_to)

        # Stale tmp should be gone; real extraction should succeed.
        assert not stale_tmp.exists()
        assert (extract_to / "world").exists()

    def test_missing_archive_raises(self, builder, tmp_path):
        with pytest.raises(SnapshotExtractionError):
            builder.extract(tmp_path / "ghost.tar.zst", tmp_path / "out")
