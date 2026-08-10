# 📦 BlockSync — Complete User & Operations Guide

Welcome to **BlockSync**! This guide explains everything you need to know about setting up, configuring, running, and playing Minecraft using BlockSync with your friends.

---

## 📖 Table of Contents

1. [Overview & Concept](#-overview--concept)
2. [How BlockSync Works](#-how-blocksync-works)
3. [Prerequisites](#-prerequisites)
4. [Quick Start (Mock Mode / UI Demo)](#-quick-start-mock-mode--ui-demo)
5. [Full Setup Guide (Real Hosting)](#-full-setup-guide-real-hosting)
   - [1. Google Drive Setup](#1-google-drive-setup)
   - [2. Local Minecraft Server Setup](#2-local-minecraft-server-setup)
   - [3. Radmin VPN Setup](#3-radmin-vpn-setup)
6. [Running BlockSync](#-running-blocksync)
7. [Host vs. Player Workflows](#-host-vs-player-workflows)
8. [Troubleshooting & Error Handling](#-troubleshooting--error-handling)
9. [Environment Variables Reference](#-environment-variables-reference)

---

## 💡 Overview & Concept

**BlockSync** is a desktop application designed for a trusted group of friends to share and host **one single Minecraft Java Edition world** without needing a paid 24/7 server host (like Aternos, Realm, or Nitrado).

The world is saved and synced via a shared **Google Drive** folder.

### The Fundamental Invariant
> ⚠️ **ONE WORLD → ONE COMMITTED VERSION → ONE ACTIVE HOST → ONE AUTHORITATIVE MINECRAFT PROCESS.**

BlockSync guarantees that only **one machine** runs and modifies the world at any given time. There is no server split, no progress loss, and no accidental overwrites.

---

## ⚙️ How BlockSync Works

```text
               Google Drive (Shared Folder)
              ┌───────────────────────────┐
              │  - manifest.json          │
              │  - lock.json              │
              │  - snapshots/world-v*.zst │
              └─────────────┬─────────────┘
                            │
               ┌────────────┴────────────┐
               │  Active Host (e.g. Alice)│
               │  - Lock acquired         │
               │  - Runs MC Server jar    │
               └────────────┬────────────┘
                            │ (Radmin VPN Network)
             ┌──────────────┼──────────────┐
             ▼              ▼              ▼
           Bob           Charlie          Dave
      (Connect to Alice's Radmin IP:25565 via MC Multiplayer)
```

When **Alice** finishes hosting:
1. Minecraft server saves chunk data (`save-all flush`).
2. Minecraft server stops cleanly.
3. BlockSync creates a compressed `.tar.zst` snapshot of the world.
4. BlockSync uploads snapshot to Google Drive & updates `manifest.json`.
5. Lock is released.

When **Bob** wants to host next:
1. BlockSync checks Google Drive, sees Bob is up to date (or downloads latest v185 snapshot).
2. Bob acquires the host lock.
3. Bob's local Minecraft server starts automatically.
4. Friends now join Bob's Radmin IP!

---

## 🛠️ Prerequisites

Before getting started, make sure every player has installed:

1. **Python 3.11+** installed on Windows.
2. **Java 21** (or Java matching your target Minecraft version).
3. **Radmin VPN** (free virtual LAN software for direct peer-to-peer connection).
4. **Minecraft Java Edition** client.

---

## 🚀 Quick Start (Mock Mode / UI Demo)

Want to try out the interface and see how BlockSync feels before configuring Google Drive? You can run it instantly in **Mock Mode**:

```powershell
# 1. Open PowerShell and navigate to the project root
cd "c:\Users\sanat\Desktop\minecraft project\aternos-killer"

# 2. Create & activate Python virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Install requirements
pip install -r requirements.txt

# 4. Launch BlockSync!
python main.py
```

> 🎯 **Note**: In Mock Mode, all world downloads, hosting states, server logs, and locking are simulated locally. No real network or Drive API is required!

---

## 🔧 Full Setup Guide (Real Hosting)

To use BlockSync with your actual Minecraft world across machines, follow these steps:

### 1. Google Drive Setup

You need **one** Google Cloud Service Account key shared with your group's folder.

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project (name it e.g. `BlockSync`).
3. Enable **Google Drive API** (`APIs & Services` → `Library` → search `Google Drive API` → Enable).
4. Create a Service Account (`APIs & Services` → `Credentials` → `Create Credentials` → `Service Account`).
5. Click your new Service Account → go to **Keys** tab → **Add Key** → **Create new key (JSON)**.
6. Save the downloaded `.json` file to a secure local folder on your PC (e.g. `C:\secrets\service_account.json`).
   *⚠️ NEVER commit this JSON file to git!*
7. Open Google Drive in your browser, create a folder named `BlockSync-World`.
8. Copy the Service Account email address (found inside your `.json` file, e.g. `blocksync@project.iam.gserviceaccount.com`).
9. **Share the Drive folder** with this email address and grant **Editor** permissions.
10. Copy the **Folder ID** from your browser address bar:
    `https://drive.google.com/drive/folders/1a2b3c4d5e6f7g8h9...` (The string after `/folders/` is your `BLOCKSYNC_GDRIVE_FOLDER_ID`).

---

### 2. Local Minecraft Server Setup

Each machine that intends to **Host** needs a working server directory.

1. Create a folder for the server, e.g. `C:\mc-server`.
2. Automatically download the server JAR for your version using our built-in script:
   ```powershell
   .\.venv\Scripts\python -c "from pathlib import Path; from minecraft.jar_downloader import JarDownloader; JarDownloader(Path('C:/mc-server')).ensure_jar('1.21.4')"
   ```
3. Accept Mojang's EULA by creating `eula.txt` inside `C:\mc-server`:
   ```powershell
   Set-Content -Path "C:\mc-server\eula.txt" -Value "eula=true"
   ```
4. Verify that `C:\mc-server\server.jar` and `C:\mc-server\eula.txt` exist.

---

### 3. Radmin VPN Setup

1. Download and install [Radmin VPN](https://www.radmin-vpn.com/).
2. Create a private network (e.g. Name: `BlockSync-Group`, Password: `...`).
3. Have all your friends join the same Radmin network.
4. Radmin will assign each person a virtual IP address (e.g. `26.x.x.x`). BlockSync automatically detects your Radmin IP address!

---

## 🎮 Running BlockSync

To run BlockSync in **Real Mode** connected to your Google Drive folder, configure environment variables before launching:

```powershell
# Set Environment Variables
$env:BLOCKSYNC_USE_MOCKS        = "0"
$env:BLOCKSYNC_WORLD_ID         = "survival"
$env:BLOCKSYNC_WORLD_DIR        = "C:\mc-server\world"
$env:BLOCKSYNC_SERVER_DIR       = "C:\mc-server"
$env:BLOCKSYNC_GDRIVE_FOLDER_ID = "YOUR_GOOGLE_DRIVE_FOLDER_ID_HERE"
$env:BLOCKSYNC_CREDENTIALS_FILE = "C:\secrets\service_account.json"
$env:BLOCKSYNC_MC_VERSION       = "1.21.4"

# Launch Application
python main.py
```

---

## 🔄 Host vs. Player Workflows

### 🏠 If you want to HOST:
1. Open BlockSync.
2. Click **Host World**.
3. BlockSync will:
   - Check if anyone else is hosting (acquire host lock).
   - Check if your local world is up to date (download latest from Drive if needed).
   - Safely launch the Minecraft Server process.
   - Wait until server is ready (`Done (X.Xs)!`).
4. Share your **Connection Address** (shown on screen, e.g. `26.12.34.56:25565`) with your friends.
5. Play Minecraft!
6. When done, click **Stop & Save World** in BlockSync.
7. BlockSync will save the game, stop the process, package the snapshot, upload to Drive, and release the host lock.

### 🎮 If you want to JOIN someone hosting:
1. Open BlockSync.
2. If another friend (e.g. Alice) is hosting, the Home Screen will display:
   - Status: **Alice's PC is hosting**
3. Click **Join Session**.
4. Click **Copy Address** to copy Alice's server address to your clipboard.
5. Open Minecraft Java Edition → **Multiplayer** → **Direct Connection** (or Add Server) → Paste address (`Ctrl+V`) → Connect!

---

## 🛡️ Troubleshooting & Error Handling

| Issue | Cause | Resolution |
|---|---|---|
| **Lock Conflict** | Another friend is currently hosting the world. | Wait for them to finish hosting or check the Join screen to copy their IP. |
| **World Conflict** | Local world and remote world histories have diverged. | BlockSync prevents overwriting to protect world data. Inspect versions and manually sync files if necessary. |
| **Local World Ahead** | A previous upload was interrupted or incomplete. | Re-run BlockSync or verify Drive snapshot files before hosting. |
| **Minecraft Server Crash** | Crash detected during server startup or gameplay. | BlockSync safely reverts state to `ERROR` and preserves the last committed Google Drive version intact. |
| **Drive Unavailable** | No network or invalid credentials key. | BlockSync aborts host start without destroying local data. Check internet connection & credentials JSON path. |

---

## 📋 Environment Variables Reference

| Variable | Default | Description |
|---|---|---|
| `BLOCKSYNC_USE_MOCKS` | `1` | Set to `0` for Real Mode, `1` for simulated Mock Mode. |
| `BLOCKSYNC_WORLD_ID` | `survival` | Unique key identifying your world dataset. |
| `BLOCKSYNC_WORLD_DIR` | `None` | Path to active world folder (e.g., `C:\mc-server\world`). |
| `BLOCKSYNC_SERVER_DIR` | `None` | Path to server directory containing `server.jar`. |
| `BLOCKSYNC_GDRIVE_FOLDER_ID` | `None` | The shared Google Drive folder ID string. |
| `BLOCKSYNC_CREDENTIALS_FILE` | `None` | Path to Google Service Account `.json` file. |
| `BLOCKSYNC_MC_VERSION` | `1.21.4` | Target Minecraft version string. |
| `BLOCKSYNC_SERVER_PORT` | `25565` | Server port used by Minecraft. |
| `BLOCKSYNC_STATIC_NETWORK` | `0` | Set `1` to override Radmin auto-detection with static IP. |
| `BLOCKSYNC_STATIC_IP` | `10.0.0.2` | Static IP value when static network is enabled. |

---

*Happy Gaming! ⛏️💎*
