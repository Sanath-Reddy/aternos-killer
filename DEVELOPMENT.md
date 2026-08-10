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
  `session/lock.py`, `world/manager.py`, or `minecraft/manager.py` directly
  from UI screens / view-models.
- **DO** import only from `core.session_service`, `core.world_service`,
  `core.minecraft_service`, plus Developer 2’s own `ui/` and `network/`.
- Wiring of real core objects happens only in `ui/app_services.py`.
- If you need a new capability exposed, ask Developer 1 to add it to a service
  (see **UI Integration Requests** below).
- If Developer 1 changes a service method signature, it will be documented here
  immediately and a `BREAKING CHANGE` comment added to the service file.

---

## Running the UI (Developer 2)

```powershell
cd aternos-killer
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

By default the UI uses **mock services** so you can exercise Host / Join /
STOP & SAVE without Drive credentials or a Minecraft JAR.

### Useful environment variables

| Variable | Default | Purpose |
|---|---|---|
| `BLOCKSYNC_USE_MOCKS` | `1` | Set `0` to attempt real core wiring |
| `BLOCKSYNC_STATIC_NETWORK` | `0` | Use a fixed demo IP instead of Radmin detection |
| `BLOCKSYNC_STATIC_IP` | `10.0.0.2` | IP when static network is enabled |
| `BLOCKSYNC_SERVER_PORT` | `25565` | Interim port until `MinecraftService.get_server_port()` exists |
| `BLOCKSYNC_MOCK_FOREIGN_HOST` | _(empty)_ | Simulate another host holding the lock |
| `BLOCKSYNC_MOCK_SYNC` | `UP_TO_DATE` | `NEEDS_UPDATE` / `CONFLICT` / `LOCAL_AHEAD` |
| `BLOCKSYNC_MOCK_LOCAL_VERSION` | `184` | Mock local world version |
| `BLOCKSYNC_MOCK_REMOTE_VERSION` | `184` | Mock remote world version |

Real mode (when `world/` is available and Drive is configured):

```powershell
$env:BLOCKSYNC_USE_MOCKS = "0"
$env:BLOCKSYNC_WORLD_ID = "survival"
$env:BLOCKSYNC_WORLD_DIR = "C:\mc-server\world"
$env:BLOCKSYNC_SERVER_DIR = "C:\mc-server"
$env:BLOCKSYNC_GDRIVE_FOLDER_ID = "<folder-id>"
$env:BLOCKSYNC_CREDENTIALS_FILE = "C:\secrets\service_account.json"
python main.py
```

If real wiring fails (missing `world/` package, incomplete env, bad credentials),
the UI logs a warning and falls back to mocks.

### UI tests

```powershell
pytest tests/test_radmin_network.py tests/test_session_vm.py -v
```

---

## UI architecture

```
main.py
  → ui.app.run_app()
      → ui.app_services.build_app_services()
      → BlockSyncApp (CustomTkinter)
           HomeScreen / HostingScreen / JoinScreen
                ↓
           SessionViewModel
                ↓
           SessionService | WorldService | MinecraftService
           NetworkManager (RadminNetworkManager)
```

- `begin_host` / `end_host` run on background threads.
- `add_state_observer` + a 2s poll keep the UI fresh.
- STOP is labeled **STOP & SAVE** (save → snapshot → upload → release lock).
- Errors show friendly copy; raw details are behind **VIEW DETAILS** / **VIEW LOG**.

### Radmin behavior

- Detect adapter name containing `Radmin VPN` (case-insensitive).
- Read IPv4 from that adapter only — never assume `26.x.x.x`.
- If unavailable: show “Not detected” and block HOST with a clear message.
- Connection address displayed as `<radmin-ip>:<port>` with **COPY ADDRESS**.

---

## UI Integration Requests (for Developer 1)

These are needed for full production UX. UI currently uses safe interim behavior.

1. **`MinecraftService.get_server_port() -> int`**  
   Read `server-port` from `server.properties`.  
   *Interim:* `BLOCKSYNC_SERVER_PORT` / default `25565`.

2. **Progress / phase callbacks on `begin_host`**  
   e.g. `acquiring_lock`, `syncing` (+ download %), `starting_minecraft`.  
   *Interim:* checklist driven by FSM `starting` → `active`.

3. **`WorldService.sync_world()`** (download/apply without hosting)  
   For Home **UPDATE WORLD**.  
   *Interim:* mock-only `sync_world()`; real mode relies on sync inside `begin_host`.

4. **Distinguish Drive unreachable vs no remote manifest**  
   Today both can look like `None` to the UI.

5. **Restore / ship the `world/` package**  
   Required for real `WorldService` / `Session` imports.

6. **Optional: host Radmin IP on the lock**  
   So joiners can show the host’s address without asking in chat.

7. **Player count** — defer until a core API exists (not required for V1).

---

## Phased Delivery

| Phase | What | Status |
|---|---|---|
| 1 | Local MC lifecycle (start → ready → save → stop) | ✅ Done |
| 2 | Local snapshots (.tar.zst create/extract/verify) | ✅ Done |
| 3 | Google Drive storage (upload/download/manifest/lock) | ✅ Done |
| 4 | Host lock + Session orchestration | ✅ Done |
| 5 | Public service APIs | ✅ Done |
| 6 | UI shell + mocks + Radmin + connection UX | ✅ Done (Dev2) |
| 7 | Failure hardening + real-mode UI verification | 🔜 Next (needs `world/`) |
