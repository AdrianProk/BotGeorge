#!/bin/sh
# Make sure the data folder (usually a bind mount like ./data) is writable by
# the unprivileged bot user, then drop root and start the bot.
set -e

DATA_DIR="${DATA_DIR:-/data}"

if [ "$(id -u)" = "0" ]; then
    mkdir -p "$DATA_DIR"
    chown -R george:george "$DATA_DIR"
    exec gosu george "$@"
fi

exec "$@"
