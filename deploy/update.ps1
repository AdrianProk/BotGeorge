# Pull the newest George image (including the latest yt-dlp) and restart if it changed.
# Schedule it with Windows Task Scheduler, e.g. daily:
#   powershell.exe -ExecutionPolicy Bypass -File C:\path\to\BotGeorge\deploy\update.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
docker compose pull
docker compose up -d
docker image prune -f
