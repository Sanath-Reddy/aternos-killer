@echo off
set BLOCKSYNC_USE_MOCKS=0
set BLOCKSYNC_WORLD_ID=survival
set BLOCKSYNC_SERVER_DIR=c:\Users\sanat\Desktop\minecraft project\mc-server
set BLOCKSYNC_WORLD_DIR=c:\Users\sanat\Desktop\minecraft project\mc-server\world
set BLOCKSYNC_GDRIVE_FOLDER_ID=1WgqyTCUd9v8lCfGg3V5RcxIR0215Cxeo
set BLOCKSYNC_CREDENTIALS_FILE=c:\Users\sanat\Desktop\minecraft project\credentials.json
set BLOCKSYNC_MC_VERSION=26.2
set BLOCKSYNC_JAVA_PATH=C:\Users\sanat\.lunarclient\jre\515e47c1d532181677af445d76add9cabc2317de\zulu25.30.17-ca-jre25.0.1-win_x64\bin\java.exe

echo Starting BlockSync in Real Mode...
.\.venv\Scripts\python main.py
pause
