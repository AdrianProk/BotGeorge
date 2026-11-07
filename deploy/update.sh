#!/bin/sh
# Pull the newest George image (including the latest yt-dlp) and restart if it changed.
# Run it by hand, or schedule it, e.g. daily with cron:
#   23 5 * * * /path/to/BotGeorge/deploy/update.sh >> /path/to/BotGeorge/data/update.log 2>&1
set -e
cd "$(dirname "$0")/.."
docker compose pull
docker compose up -d
docker image prune -f
