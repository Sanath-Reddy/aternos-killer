# BlockSync — Architecture

## Overview

BlockSync is a desktop application that lets a small trusted group share a
single Minecraft Java Edition world without a paid hosting service.  The world
is persisted in Google Drive.  Only **one machine may be the active host at any
time**.

```
Google Drive
    │
    │ latest committed world (snapshot + manifest)
    ▼
Active Host (e.g. Alice's PC)
    │
    │ Minecraft Server (Java process)
    ▼
Radmin VPN
    │
 ┌──┼──┐
Bob Charlie Dave   (join via Radmin IP)
```

---

## Invariant

> **ONE WORLD → ONE COMMITTED VERSION → ONE ACTIVE HOST → ONE AUTHORITATIVE MINECRAFT PROCESS.**

This invariant must never be violated.

---

## Repository Structure

```
aternos-killer/
├── core/                   # Public service APIs (for Developer 2 / UI)
│   ├── session_service.py
│   ├── world_service.py
│   └── minecraft_service.py
│
├── world/                  # World state, manifest, and snapshot operations
│   ├── manager.py          # WorldManager — safe world-swap orchestration
│   ├── manifest.py         # WorldManifest dataclass + validation
│   └── snapshot.py         # SnapshotBuilder (.tar.zst)
│
├── storage/                # Storage abstraction
│   ├── provider.py         # StorageProvider ABC + exceptions
│   └── gdrive.py           # GoogleDriveStorageProvider (service account)
│
├── minecraft/              # Java process management
│   ├── manager.py          # MinecraftManager
│   └── jar_downloader.py   # Download server.jar via Mojang API
│
├── session/                # Host lock + session orchestration
│   ├── state.py            # SessionFSM
│   ├── lock.py             # HostLock + LockManager
│   └── session.py          # Session orchestrator
│
├── config/
│   └── settings.py         # BlockSyncConfig
│
├── tests/
│   ├── test_state_machine.py
│   ├── test_manifest.py
│   ├── test_snapshot.py
│   ├── test_lock.py
│   └── test_minecraft_manager.py
│
├── ARCHITECTURE.md         ← this file
├── DEVELOPMENT.md
├── requirements.txt
└── main.py
```

---

## Module Responsibilities

### `config/settings.py` — `BlockSyncConfig`

Central configuration dataclass.  Holds all user-specified settings:
`world_id`, `world_dir`, `server_dir`, `gdrive_folder_id`, `credentials_file`,
`minecraft_version`, `jvm_args`, lock TTL, timeouts.

Computes derived paths: `work_dir`, `world_new_dir`, `world_backup_dir`,
`snapshots_dir`.

---

### `storage/provider.py` — `StorageProvider`

Abstract base class.  The **only** contract the rest of the app uses.

```
StorageProvider
    get_manifest()        → Optional[dict]
    update_manifest()
    upload_snapshot()     → file_id / remote path
    download_snapshot()   (verifies SHA-256 after download)
    get_lock()            → Optional[dict]
    acquire_lock()        (raises LockConflictError on contention)
    release_lock()
    refresh_lock()
```

`gdrive.py` is the only implementation.  Future replacements (S3, MinIO,
custom backend) just need to implement this ABC.

---

### `storage/gdrive.py` — `GoogleDriveStorageProvider`

Authenticates via **service account** (JSON key, never committed).
Drive folder layout:

```
<gdrive_folder_id>/
├── manifest.json
├── lock.json
└── snapshots/
    ├── world-183.tar.zst
    ├── world-184.tar.zst
    └── world-185.tar.zst
```

Uploads use resumable mode for files > 5 MB.  Downloads verify SHA-256
before replacing destination.  Lock acquisition uses optimistic
read-then-write sufficient for a trusted friend group.

---

### `world/manifest.py` — `WorldManifest`

Immutable, frozen dataclass.  Validated on every `from_dict()` call.

```json
{
  "world_id":          "survival",
  "version":           184,
  "parent_version":    183,
  "snapshot":          "snapshots/world-184.tar.zst",
  "sha256":            "<64-char hex>",
  "minecraft_version": "1.21.4",
  "created_at":        "2025-01-01T12:00:00+00:00",
  "created_by":        "alice-pc-abc123"
}
```

Invariants:
- All fields required.
- `version == parent_version + 1` (strict chain).
- `sha256` is 64-char lowercase hex.
- `created_at` is ISO-8601 timezone-aware.

`compare_to_remote()` returns one of:

| Result | Meaning |
|---|---|
| `UP_TO_DATE` | Versions match. |
| `NEEDS_UPDATE` | Remote is exactly one step ahead. |
| `CONFLICT` | Diverged histories — DO NOT auto-resolve. |
| `LOCAL_AHEAD` | Local is newer than Drive — possible incomplete upload. |
| `NO_LOCAL` | No local manifest — first-time or re-join. |

---

### `world/snapshot.py` — `SnapshotBuilder`

Creates `.tar.zst` archives using `tarfile` (stdlib) + `zstandard` (pip).

- **Create**: streams world directory → temp file → rename to final path.
- **Extract**: streams archive → `dest.tmp/` → rename to `dest/`.  Stale
  `.tmp` dirs are cleaned before each extraction.
- **Verify**: computes SHA-256 and raises `SnapshotVerificationError` on mismatch.
- **Security**: path-traversal check on every tar member.

---

### `world/manager.py` — `WorldManager`

Implements the **safe world-swap protocol**:

```
Download flow:
  1. Download .tar.zst → snapshots/
  2. Verify SHA-256
  3. Extract → world.new/
  4. Backup world/ → world.backup/    ← SAFE POINT (old world preserved)
  5. Move world.new/ → world/
  6. Save local manifest

Upload flow:
  1. Verify world/ has level.dat
  2. Create snapshot (world/ → snapshots/world-N.tar.zst)
  3. Return SnapshotResult to Session orchestrator
```

`world.backup/` is kept until `discard_backup()` is explicitly called (only
after the upload is confirmed committed).

---

### `minecraft/manager.py` — `MinecraftManager`

Manages the Java server process.

- `start()` — launches `java -jar server.jar nogui`.  Stdout/stderr merged and
  read by a daemon thread.
- `wait_until_ready()` — polls for the `Done (...)` line.
- `save()` — sends `save-all flush`, waits for `Saved the game`.
- `stop()` — sends `stop`, waits for process exit, kills if timeout.
- `send_command()` — writes to stdin.
- **Crash watchdog** daemon thread: if the process exits while status is not
  `STOPPING`, status transitions to `CRASHED`.

---

### `minecraft/jar_downloader.py` — `JarDownloader`

Downloads `server.jar` from Mojang's launcher metadata API.

```
https://launchermeta.mojang.com/mc/game/version_manifest_v2.json
  → per-version URL
    → server download URL + SHA1
      → download + verify → server.jar
```

If the existing JAR already passes SHA1 verification, the download is skipped.

---

### `session/state.py` — `SessionFSM`

Thread-safe FSM.  Invalid transitions raise `InvalidTransitionError`.

```
CLOSED → STARTING → ACTIVE → SAVING → SNAPSHOTTING → UPLOADING → CLOSED
                                                                ↘ ERROR
ERROR → CLOSED
```

Observers receive `(old_state, new_state)` callbacks.

---

### `session/lock.py` — `LockManager`

Manages the host lock via `StorageProvider`.

- `acquire()` — reads existing lock; raises `LockConflictError` if a valid
  non-expired foreign lock exists; overwrites stale locks; writes new lock.
- `release()` — deletes lock from Drive if session IDs match.
- `refresh()` — extends TTL; returns new `HostLock`.
- `get_current()` — fetches and parses current Drive lock.

---

### `session/session.py` — `Session`

The top-level orchestrator.

`begin_host()`:
1. `acquire lock`
2. `get_manifest`
3. `compare_with_remote`
4. `download if NEEDS_UPDATE / NO_LOCAL`
5. `start MC + wait_until_ready`
6. `FSM → ACTIVE`

`end_host()`:
1. `FSM → SAVING` → `save-all flush`
2. `stop MC` (verifies exit)
3. `FSM → SNAPSHOTTING` → create snapshot + hash
4. `FSM → UPLOADING` → upload + update manifest
5. `release lock`
6. `FSM → CLOSED`

---

### `core/` — Public Service APIs

The UI layer must only call these three classes:

| Class | Purpose |
|---|---|
| `SessionService` | `begin_host()`, `end_host()`, `get_state()`, `get_lock_info()`, `add_state_observer()` |
| `WorldService` | `get_local_manifest()`, `get_remote_manifest()`, `compare_versions()`, `validate_local_world()` |
| `MinecraftService` | `get_status()`, `get_log_tail()`, `send_command()`, `is_running()` |

All return types are plain `dict`/`str`/`bool`/`list` — no internal types leak
to Developer 2.

---

## Failure Handling Table

| Failure | Behavior |
|---|---|
| Download fails | Raise `SessionError`; world untouched; MC not started |
| Extraction fails | Delete `world.new/`; raise; `world/` unchanged |
| Snapshot creation fails | Raise; manifest NOT updated; MC already stopped |
| Upload fails | Keep local `.tar.zst`; manifest NOT updated; raise |
| Manifest update fails | Keep local snapshot; raise |
| MC crashes | FSM → ERROR; Drive state = last committed version |
| Local ahead of Drive | Raise `LocalWorldAheadError`; never overwrite Drive |
| Conflict detected | Raise `WorldConflictError`; manual resolution required |
| Drive unavailable | Raise `StorageUnavailableError`; no local data modified |
| Lock conflict | Raise `LockConflictError` with expiry time of current holder |

---

## Security

- Credentials file (`service_account.json`) is **never** in the repository.
  It is referenced by path at runtime.
- `.gitignore` blocks `*.json`, `service_account.json`, `credentials.json`,
  `token.json`.
- Snapshot archives guard against path traversal in tar members.
- Lock session IDs are UUIDs generated fresh each session.
