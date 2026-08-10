"""
tests/test_manifest.py — Unit tests for WorldManifest.
"""

from datetime import datetime, timezone

import pytest
from world.manifest import (
    CompareResult,
    MalformedManifestError,
    ManifestVersionError,
    WorldManifest,
)

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

VALID_DICT = {
    "world_id": "survival",
    "version": 184,
    "parent_version": 183,
    "snapshot": "snapshots/world-184.tar.zst",
    "sha256": "a" * 64,
    "minecraft_version": "1.21.4",
    "created_at": "2025-01-01T12:00:00+00:00",
    "created_by": "alice-pc-abc",
}


def make_manifest(**overrides) -> WorldManifest:
    d = {**VALID_DICT, **overrides}
    return WorldManifest.from_dict(d)


# ──────────────────────────────────────────────────────────────────────────────
# Parsing — valid
# ──────────────────────────────────────────────────────────────────────────────

class TestFromDictValid:
    def test_parses_valid_dict(self):
        m = WorldManifest.from_dict(VALID_DICT)
        assert m.world_id == "survival"
        assert m.version == 184
        assert m.parent_version == 183
        assert m.sha256 == "a" * 64

    def test_sha256_is_lowercased(self):
        d = {**VALID_DICT, "sha256": "A" * 64}
        m = WorldManifest.from_dict(d)
        assert m.sha256 == "a" * 64

    def test_naive_created_at_gets_utc(self):
        d = {**VALID_DICT, "created_at": "2025-01-01T12:00:00"}
        m = WorldManifest.from_dict(d)
        assert m.created_at.tzinfo is not None

    def test_version_1_parent_0_is_valid(self):
        d = {**VALID_DICT, "version": 1, "parent_version": 0}
        m = WorldManifest.from_dict(d)
        assert m.version == 1


# ──────────────────────────────────────────────────────────────────────────────
# Parsing — invalid
# ──────────────────────────────────────────────────────────────────────────────

class TestFromDictInvalid:
    @pytest.mark.parametrize("missing_field", [
        "world_id", "version", "parent_version", "snapshot",
        "sha256", "minecraft_version", "created_at", "created_by",
    ])
    def test_missing_required_field(self, missing_field):
        d = {k: v for k, v in VALID_DICT.items() if k != missing_field}
        with pytest.raises(MalformedManifestError):
            WorldManifest.from_dict(d)

    def test_empty_world_id(self):
        with pytest.raises(MalformedManifestError):
            WorldManifest.from_dict({**VALID_DICT, "world_id": ""})

    def test_empty_created_by(self):
        with pytest.raises(MalformedManifestError):
            WorldManifest.from_dict({**VALID_DICT, "created_by": "  "})

    def test_version_zero_rejected(self):
        with pytest.raises(MalformedManifestError):
            WorldManifest.from_dict({**VALID_DICT, "version": 0, "parent_version": -1})

    def test_version_not_parent_plus_one(self):
        with pytest.raises(ManifestVersionError):
            WorldManifest.from_dict({**VALID_DICT, "version": 184, "parent_version": 100})

    def test_bad_sha256_length(self):
        with pytest.raises(MalformedManifestError):
            WorldManifest.from_dict({**VALID_DICT, "sha256": "abc123"})

    def test_bad_sha256_non_hex(self):
        with pytest.raises(MalformedManifestError):
            WorldManifest.from_dict({**VALID_DICT, "sha256": "g" * 64})

    def test_bad_created_at(self):
        with pytest.raises(MalformedManifestError):
            WorldManifest.from_dict({**VALID_DICT, "created_at": "not-a-date"})

    def test_version_not_integer(self):
        with pytest.raises(MalformedManifestError):
            WorldManifest.from_dict({**VALID_DICT, "version": "184", "parent_version": "183"})


# ──────────────────────────────────────────────────────────────────────────────
# Serialisation roundtrip
# ──────────────────────────────────────────────────────────────────────────────

class TestRoundtrip:
    def test_to_dict_and_back(self):
        m = WorldManifest.from_dict(VALID_DICT)
        d = m.to_dict()
        m2 = WorldManifest.from_dict(d)
        assert m == m2

    def test_to_dict_keys(self):
        m = WorldManifest.from_dict(VALID_DICT)
        d = m.to_dict()
        for key in VALID_DICT:
            assert key in d


# ──────────────────────────────────────────────────────────────────────────────
# is_direct_successor_of
# ──────────────────────────────────────────────────────────────────────────────

class TestSuccessor:
    def test_direct_successor(self):
        m184 = make_manifest(version=184, parent_version=183)
        m185 = make_manifest(version=185, parent_version=184)
        assert m185.is_direct_successor_of(m184)

    def test_not_successor_version_gap(self):
        m184 = make_manifest(version=184, parent_version=183)
        m186 = make_manifest(version=186, parent_version=185)
        assert not m186.is_direct_successor_of(m184)

    def test_not_successor_different_world(self):
        m184 = make_manifest(version=184, parent_version=183, world_id="survival")
        m185_other = make_manifest(version=185, parent_version=184, world_id="creative")
        assert not m185_other.is_direct_successor_of(m184)


# ──────────────────────────────────────────────────────────────────────────────
# compare_to_remote
# ──────────────────────────────────────────────────────────────────────────────

class TestCompareToRemote:
    def test_up_to_date(self):
        m = make_manifest(version=184, parent_version=183)
        assert m.compare_to_remote(m) == CompareResult.UP_TO_DATE

    def test_needs_update(self):
        local  = make_manifest(version=184, parent_version=183)
        remote = make_manifest(version=185, parent_version=184)
        assert local.compare_to_remote(remote) == CompareResult.NEEDS_UPDATE

    def test_needs_update_multi_version_gap(self):
        local  = make_manifest(version=184, parent_version=183)
        remote = make_manifest(version=186, parent_version=185)
        assert local.compare_to_remote(remote) == CompareResult.NEEDS_UPDATE

    def test_local_ahead(self):
        local  = make_manifest(version=185, parent_version=184)
        remote = make_manifest(version=184, parent_version=183)
        assert local.compare_to_remote(remote) == CompareResult.LOCAL_AHEAD

    def test_conflict(self):
        local  = make_manifest(version=184, parent_version=183, sha256="a" * 64)
        remote = make_manifest(version=184, parent_version=183, sha256="b" * 64)
        result = local.compare_to_remote(remote)
        assert result == CompareResult.CONFLICT

    def test_no_remote(self):
        local = make_manifest(version=184, parent_version=183)
        assert local.compare_to_remote(None) == CompareResult.LOCAL_AHEAD


# ──────────────────────────────────────────────────────────────────────────────
# make_next
# ──────────────────────────────────────────────────────────────────────────────

class TestMakeNext:
    def test_version_incremented(self):
        m = make_manifest(version=184, parent_version=183)
        nxt = m.make_next(
            snapshot="snapshots/world-185.tar.zst",
            sha256="b" * 64,
            created_by="bob-pc",
        )
        assert nxt.version == 185
        assert nxt.parent_version == 184
        assert nxt.created_by == "bob-pc"

    def test_next_is_valid(self):
        m = make_manifest(version=184, parent_version=183)
        nxt = m.make_next("snapshots/world-185.tar.zst", "b" * 64, "bob")
        # Should not raise.
        WorldManifest.from_dict(nxt.to_dict())
