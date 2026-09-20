#!/bin/sh
# Container entrypoint: apply PUID/PGID/UMASK, back up the DB, migrate, then start the app.
set -eu

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
UMASK="${UMASK:-022}"

groupmod -o -g "$PGID" app
usermod -o -u "$PUID" app
umask "$UMASK"

mkdir -p /config/backups
chown app:app /config /config/backups

# The download folders (requirements §7.6). A fresh volume or host folder belongs to
# root, so the app user could not write into it. Only these folders are chowned, never
# their contents, so media Radarr/Sonarr owns is left alone. A chown that fails (a
# read-only or foreign-owned mount) is reported by the startup self-test, not fatal here.
COMPLETED_DIR="${COMPLETED_DIR:-/web-downloads/completed}"
INCOMPLETE_DIR="${INCOMPLETE_DIR:-/web-downloads/incomplete}"
for dir in "$INCOMPLETE_DIR" "$COMPLETED_DIR" "$COMPLETED_DIR/movies" \
  "$COMPLETED_DIR/tv-shows" "$COMPLETED_DIR/other"; do
  mkdir -p "$dir" 2>/dev/null || true
  [ -d "$dir" ] && chown app:app "$dir" 2>/dev/null || true
done

cd /app
gosu app python -m app.db.backup
gosu app alembic upgrade head

if [ "$#" -gt 0 ]; then
  exec gosu app "$@"
fi
# Single process only (requirements §6.1): the job runner and its in-memory state assume it.
exec gosu app uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
