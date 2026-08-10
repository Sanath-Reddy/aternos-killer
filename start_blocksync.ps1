# BlockSync Real Mode Launcher
$env:BLOCKSYNC_USE_MOCKS        = "0"
$env:BLOCKSYNC_WORLD_ID         = "survival"
$env:BLOCKSYNC_SERVER_DIR       = "c:\Users\sanat\Desktop\minecraft project\mc-server"
$env:BLOCKSYNC_WORLD_DIR        = "c:\Users\sanat\Desktop\minecraft project\mc-server\world"
$env:BLOCKSYNC_GDRIVE_FOLDER_ID = "1WgqyTCUd9v8lCfGg3V5RcxIR0215Cxeo"
$env:BLOCKSYNC_CREDENTIALS_FILE = "c:\Users\sanat\Desktop\minecraft project\credentials.json"
$env:BLOCKSYNC_MC_VERSION       = "26.2"
$env:BLOCKSYNC_JAVA_PATH        = "C:\Users\sanat\.lunarclient\jre\515e47c1d532181677af445d76add9cabc2317de\zulu25.30.17-ca-jre25.0.1-win_x64\bin\java.exe"

Write-Host "Starting BlockSync in Real Mode..." -ForegroundColor Green
.\.venv\Scripts\python main.py
