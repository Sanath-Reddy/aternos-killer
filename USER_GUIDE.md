# 📦 BlockSync — Complete User & Operations Guide

Welcome to **BlockSync**! BlockSync lets a trusted group of friends share and host **one single Minecraft Java Edition world** via Google Drive without paying for dedicated hosting.

---

## 📖 Table of Contents

1. [Overview & Concept](#-overview--concept)
2. [How to Give BlockSync a World](#-how-to-give-blocksync-a-world)
   - [Option A: Starting Fresh (New World)](#option-a-starting-fresh-new-world)
   - [Option B: Using an Existing Singleplayer World](#option-b-using-an-existing-singleplayer-world)
   - [Option C: Using an Existing Server World](#option-c-using-an-existing-server-world)
3. [Step-by-Step: How to Play Together](#-step-by-step-how-to-play-together)
   - [Step 1: Host Launches BlockSync](#step-1-host-launches-blocksync)
   - [Step 2: Host Starts the Server](#step-2-host-starts-the-server)
   - [Step 3: Host & Friends Connect in Minecraft](#step-3-host--friends-connect-in-minecraft)
   - [Step 4: Ending the Session (Saving & Uploading)](#step-4-ending-the-session-saving--uploading)
   - [Step 5: Handoff to Next Host (e.g., Alice → Bob)](#step-5-handoff-to-next-host-eg-alice--bob)
4. [Prerequisites & Setup](#-prerequisites--setup)
5. [Running BlockSync](#-running-blocksync)
6. [Troubleshooting & Conflict Resolution](#-troubleshooting--conflict-resolution)
7. [Environment Variables Reference](#-environment-variables-reference)

---

## 💡 Overview & Concept

### The Fundamental Invariant
> ⚠️ **ONE WORLD → ONE COMMITTED VERSION → ONE ACTIVE HOST → ONE AUTHORITATIVE MINECRAFT PROCESS.**

BlockSync guarantees that only **one machine** hosts and writes to the world at any given time. There is no progress loss, no world duplication, and no paid hosting required.

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

---

## 🗺️ How to Give BlockSync a World

BlockSync looks for the active world inside your configured server directory at:
📍 `c:\Users\sanat\Desktop\minecraft project\mc-server\world`

### Option A: Starting Fresh (New World)
If `mc-server\world` does not exist:
- **Do nothing!** When the host clicks **Host World** for the first time, Minecraft will automatically generate a brand new world folder with a random seed.

### Option B: Using an Existing Singleplayer World
If you have a world from Singleplayer you want to play together:
1. Open Windows Run (`Win + R`), type `%appdata%\.minecraft\saves`, and press **Enter**.
2. Find your world folder (e.g., `MySurvivalWorld`).
3. Copy all files inside `MySurvivalWorld` into:
   `c:\Users\sanat\Desktop\minecraft project\mc-server\world`
4. Ensure `level.dat` is directly inside `mc-server\world\` (e.g., `mc-server\world\level.dat`).

### Option C: Using an Existing Server World
If you have a world from another server or Aternos export:
1. Extract/copy the world folder into `c:\Users\sanat\Desktop\minecraft project\mc-server\world`.
2. Ensure files like `level.dat`, `region/`, `playerdata/` are located in `mc-server\world\`.

> 💡 **First Host Sync**: When the host starts BlockSync for the first time with a local world, BlockSync packages it into **Snapshot Version 1**, uploads it to your Google Drive folder, and creates `manifest.json`.

---

## 🎮 Step-by-Step: How to Play Together

### Step 1: Host Launches BlockSync
Double-click **`start_blocksync.bat`** (or run `.\start_blocksync.ps1` in PowerShell) inside the `aternos-killer` folder.

### Step 2: Host Starts the Server
1. Click **Host World** in the BlockSync interface.
2. BlockSync automatically:
   - Acquires the host lock on Google Drive.
   - Checks Google Drive for newer versions (and downloads them if needed).
   - Launches Minecraft Server `server.jar` in the background.
3. Wait until the Status badge changes to **`Online`** (Console log shows `Done (X.Xs)!`).

### Step 3: Host & Friends Connect in Minecraft
1. Look at the **Connection Address** box in BlockSync (e.g. `26.12.34.56:25565`).
2. Open **Minecraft Java Edition (v1.21.4)**.
3. Go to **Multiplayer** → **Direct Connection** (or **Add Server**).
4. Enter the address:
   - **Friends (Joining over Radmin VPN)**: Enter Host's Radmin IP address (e.g. `26.12.34.56:25565`).
   - **Host (Same PC)**: Enter `127.0.0.1:25565` or `localhost`.
5. Click **Join Server** and play together!

### Step 4: Ending the Session (Saving & Uploading)
1. When everyone is done playing, all players leave the Minecraft server.
2. Host clicks **Stop & Save World** in BlockSync.
3. BlockSync automatically:
   - Sends `save-all flush` to Minecraft to force a full save.
   - Gracefully stops the server process.
   - Creates a compressed `.tar.zst` snapshot.
   - Uploads the new snapshot to Google Drive & updates `manifest.json`.
   - Releases the host lock on Drive.

### Step 5: Handoff to Next Host (e.g., Alice → Bob)
Next time your group plays:
1. **Bob** opens BlockSync on his computer.
2. Bob clicks **Host World**.
3. BlockSync sees that Alice uploaded **Version 2** to Google Drive.
4. BlockSync automatically downloads Version 2 to Bob's PC, extracts it safely, acquires the lock, and starts Minecraft.
5. Everyone (including Alice) now connects to **Bob's Radmin IP**!

---

## 🛠️ Prerequisites & Setup

Every player needs:
1. **Python 3.11+** installed on Windows.
2. **Java 21** (or Java matching your Minecraft version).
3. **Radmin VPN** (free LAN software connecting all friends on the same virtual network).
4. **Minecraft Java Edition** client.

---

## 🚀 Running BlockSync

### Launcher Scripts
Inside `c:\Users\sanat\Desktop\minecraft project\aternos-killer`:
- **`start_blocksync.bat`**: Double-click to launch in Real Mode.
- **`start_blocksync.ps1`**: Run in PowerShell to launch in Real Mode.

### Real Mode Configured Settings:
- **Server Directory**: `c:\Users\sanat\Desktop\minecraft project\mc-server`
- **World Directory**: `c:\Users\sanat\Desktop\minecraft project\mc-server\world`
- **Google Drive Folder ID**: `1WgqyTCUd9v8lCfGg3V5RcxIR0215Cxeo`
- **Credentials File**: `c:\Users\sanat\Desktop\minecraft project\aternos-killer-a1e05fa021cf.json`

---

## 🛡️ Troubleshooting & Conflict Resolution

| Issue | Cause | Solution |
|---|---|---|
| **Lock Conflict** | Another friend is currently hosting the world. | Wait for them to stop hosting, or click **Join Session** to get their IP. |
| **World Conflict** | Local world and remote world histories have diverged. | BlockSync prevents overwriting to protect world data. Manually check snapshots on Drive or compare version numbers before continuing. |
| **Local World Ahead** | A previous upload was interrupted or incomplete. | Inspect local snapshot files or re-run host shutdown cleanly. |
| **Server Crash** | Server crashed during gameplay. | BlockSync moves state to `ERROR`. Drive contains the last committed safe snapshot intact. |
| **Cannot Connect in MC** | Host's Radmin VPN is disconnected or Windows Firewall is blocking port `25565`. | Ensure Radmin VPN is turned ON for all players and allow Java through Windows Firewall. |

---

## 📋 Environment Variables Reference

| Variable | Default | Description |
|---|---|---|
| `BLOCKSYNC_USE_MOCKS` | `1` | Set to `0` for Real Mode, `1` for simulated Mock Mode. |
| `BLOCKSYNC_WORLD_ID` | `survival` | Logical identifier for your world. |
| `BLOCKSYNC_WORLD_DIR` | `None` | Path to active world directory (`.../mc-server/world`). |
| `BLOCKSYNC_SERVER_DIR` | `None` | Path to server directory containing `server.jar`. |
| `BLOCKSYNC_GDRIVE_FOLDER_ID` | `None` | Shared Google Drive folder ID. |
| `BLOCKSYNC_CREDENTIALS_FILE` | `None` | Absolute path to Google service account JSON key. |
| `BLOCKSYNC_MC_VERSION` | `1.21.4` | Target Minecraft version string. |
| `BLOCKSYNC_SERVER_PORT` | `25565` | Server port used by Minecraft. |

---

*Happy Gaming! ⛏️💎*
