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

cd /app
gosu app python -m app.db.backup
gosu app alembic upgrade head

if [ "$#" -gt 0 ]; then
  exec gosu app "$@"
fi
# Single process only (requirements §6.1): the job runner and its in-memory state assume it.
exec gosu app uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
