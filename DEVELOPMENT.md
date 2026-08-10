# BlockSync — Development Guide

## Prerequisites

- Python 3.11+
- Java 21+ (for running Minecraft server locally)
- A Google Cloud project with the Drive API enabled
- A service account JSON key (see _Google Drive Setup_ below)

---

## Setup

### 1. Clone and install dependencies

```powershell
git clone https://github.com/Sanath-Reddy/aternos-killer
cd aternos-killer
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Google Drive Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project (or use an existing one).
3. Enable the **Google Drive API** (`APIs & Services → Library`).
4. Create a **Service Account** (`APIs & Services → Credentials → Create Credentials → Service Account`).
5. Download the **JSON key** for the service account.
6. Store the key somewhere safe (e.g. `C:\Users\<you>\blocksync_service_account.json`).
   **NEVER put it inside the repo directory.**
7. Create a shared folder in your personal Drive.
8. Share the folder with the service account's email address (give **Editor** permission).
9. Copy the folder ID from the URL: `https://drive.google.com/drive/folders/<FOLDER_ID>`

### 3. Provide a Minecraft Server JAR

Option A — **Auto-download** (recommended):

```python
from pathlib import Path
from minecraft.jar_downloader import JarDownloader

dl = JarDownloader(server_dir=Path("C:/mc-server"))
dl.ensure_jar(version="1.21.4")   # downloads + verifies via Mojang API
```

Option B — Manual: place `server.jar` inside your server directory, then run
it once to generate `eula.txt` and accept the EULA.

### 4. Accept the EULA

Minecraft requires you to accept the EULA before the server will start:

```
# Inside your server directory:
echo eula=true > eula.txt
```

---

## Running the Tests

```powershell
pytest tests/ -v
```

Expected output: all tests pass without a running Minecraft server or Drive
credentials.  Tests use mocked subprocesses and providers.

### Selecting specific test files

```powershell
pytest tests/test_state_machine.py -v
pytest tests/test_manifest.py -v
pytest tests/test_snapshot.py -v      # creates real .tar.zst in tmp dirs
pytest tests/test_lock.py -v
pytest tests/test_minecraft_manager.py -v
```

---

## Using the Core Services (Developer 2 Integration Guide)

### Wire up the stack

```python
from pathlib import Path

from config.settings import BlockSyncConfig
from storage.gdrive import GoogleDriveStorageProvider
from world.manager import WorldManager
from world.snapshot import SnapshotBuilder
from minecraft.manager import MinecraftManager
from session.lock import LockManager
from session.session import Session
from core.session_service import SessionService
from core.world_service import WorldService
from core.minecraft_service import MinecraftService

cfg = BlockSyncConfig(
    world_id="survival",
    world_dir=Path("C:/mc-server/world"),
    server_dir=Path("C:/mc-server"),
    gdrive_folder_id="1ABC...xyz",
    credentials_file=Path("C:/secrets/service_account.json"),
    minecraft_version="1.21.4",
    jvm_args=["-Xmx4G", "-Xms1G"],
)
cfg.validate()
cfg.ensure_work_dirs()

provider = GoogleDriveStorageProvider(
    folder_id=cfg.gdrive_folder_id,
    credentials_file=cfg.credentials_file,
)

snapshot_builder = SnapshotBuilder()
world_mgr = WorldManager(
    world_dir=cfg.world_dir,
    work_dir=cfg.work_dir,
    snapshots_dir=cfg.snapshots_dir,
    snapshot_builder=snapshot_builder,
)

mc_mgr = MinecraftManager(
    server_dir=cfg.server_dir,
    server_jar=cfg.server_jar,
    java_path=cfg.java_path,
    jvm_args=cfg.jvm_args,
    ready_timeout=cfg.ready_timeout,
    stop_timeout=cfg.stop_timeout,
    save_timeout=cfg.save_timeout,
)

lock_mgr = LockManager(provider=provider, config=cfg)

session = Session(
    config=cfg,
    provider=provider,
    world_manager=world_mgr,
    minecraft_manager=mc_mgr,
    lock_manager=lock_mgr,
)

# Public services for the UI:
session_svc  = SessionService(session)
world_svc    = WorldService(world_mgr, provider)
mc_svc       = MinecraftService(mc_mgr)
```

### Starting a host session

```python
result = session_svc.begin_host()
if result["ok"]:
    print("Server is running! State:", result["state"])
else:
    print("Failed:", result["error"])
    print("Type:", result["error_type"])   # "lock_conflict", "WorldConflictError", etc.
```

### Ending a host session

```python
result = session_svc.end_host()
if result["ok"]:
    print(f"Session closed. World committed at version {result['version']}.")
else:
    print("Shutdown error:", result["error"])
```

### Reading state

```python
state = session_svc.get_state()   # "closed" | "starting" | "active" | ...
lock  = session_svc.get_lock_info()
# lock = {"world_id": ..., "host_id": ..., "seconds_remaining": 3598.0, ...}

compare = world_svc.compare_versions()
# compare = {"result": "NEEDS_UPDATE", "local_version": 184, "remote_version": 185}

mc_status = mc_svc.get_status()   # "offline" | "starting" | "online" | ...
log = mc_svc.get_log_tail(n=100)
```

### Subscribing to state changes (for live UI updates)

```python
def on_state_change(old: str, new: str):
    print(f"[UI] Session state: {old} → {new}")

session_svc.add_state_observer(on_state_change)
```

### Sending a server command

```python
result = mc_svc.send_command("say Hello from BlockSync!")
# result = {"ok": True} or {"ok": False, "error": "..."}
```

---

## Error Recovery

If the session enters `"error"` state (MC crash, upload failure, etc.):

```python
session_svc.reset_error()   # transitions ERROR → CLOSED
# Now you can call begin_host() again
```

If an upload failed mid-way, the local snapshot is preserved in
`cfg.snapshots_dir`.  On next `end_host()`, a new snapshot will be created
and uploaded.

---

## State Machine Reference

```
CLOSED
  │ begin_host()
  ▼
STARTING
  │ MC ready
  ▼
ACTIVE
  │ end_host()
  ▼
SAVING
  │ save confirmed
  ▼
SNAPSHOTTING
  │ snapshot created
  ▼
UPLOADING
  │ upload + manifest committed
  ▼
CLOSED

Any state ──→ ERROR (on failure)
ERROR      ──→ CLOSED (via reset_error())
```

---

## World Safety Guarantees

1. **Download never destroys the active world** until the new one is fully
   extracted and verified (`world.backup/` exists during transition).
2. **Manifest is never updated** unless the snapshot upload is confirmed.
3. **Minecraft is never started** if the world download/extraction fails.
4. **Conflicts are never auto-resolved** — `WorldConflictError` is always raised.
5. **Local-ahead state is always reported** — `LocalWorldAheadError` stops the flow.

---

## Adding a New Storage Backend

1. Create `storage/your_backend.py`.
2. Implement `StorageProvider` (all 7 abstract methods).
3. Instantiate your class instead of `GoogleDriveStorageProvider` in the
   wiring code above.
4. No other files need to change.

---

## Repository Rules for Developer 2

- **DO NOT** import from `storage/gdrive.py`, `session/session.py`,
  `session/lock.py`, `world/manager.py`, or `minecraft/manager.py` directly.
- **DO** import only from `core/session_service.py`, `core/world_service.py`,
  `core/minecraft_service.py`.
- If you need a new capability exposed, ask Developer 1 to add it to a service.
- If Developer 1 changes a service method signature, it will be documented here
  immediately and a `BREAKING CHANGE` comment added to the service file.

---

## Phased Delivery

| Phase | What | Status |
|---|---|---|
| 1 | Local MC lifecycle (start → ready → save → stop) | ✅ Done |
| 2 | Local snapshots (.tar.zst create/extract/verify) | ✅ Done |
| 3 | Google Drive storage (upload/download/manifest/lock) | ✅ Done |
| 4 | Host lock + Session orchestration | ✅ Done |
| 5 | Public service APIs | ✅ Done |
| 6 | Failure hardening + retry + UI integration | 🔜 Next |
