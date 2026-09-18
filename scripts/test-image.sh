#!/usr/bin/env bash
# Checks a built fetcharr image: bundled tools, /healthz smoke test, the fetcharr CLI, PUID/PGID handling,
# pre-migration DB backups and that no local-only file got into the image.
# Usage: scripts/test-image.sh [image]   (default: fetcharr:dev)
set -euo pipefail

IMAGE="${1:-fetcharr:dev}"
RUN_ID="fetcharr-test-$$"
PORT="${SMOKE_PORT:-18000}"
CONTAINERS=()
VOLUMES=()

cleanup() {
  for c in "${CONTAINERS[@]+"${CONTAINERS[@]}"}"; do docker rm -f "$c" >/dev/null 2>&1 || true; done
  for v in "${VOLUMES[@]+"${VOLUMES[@]}"}"; do docker volume rm -f "$v" >/dev/null 2>&1 || true; done
}
trap cleanup EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "ok   $*"; }

wait_healthy() {  # container, port
  for _ in $(seq 1 60); do
    if curl -fsS "http://localhost:$2/healthz" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  docker logs "$1" >&2 || true
  return 1
}

in_image() { docker run --rm --platform linux/amd64 --entrypoint "" "$IMAGE" "$@"; }

# --- tools ------------------------------------------------------------------
in_image /opt/yt-dlp/bin/yt-dlp --version >/dev/null || fail "yt-dlp"
in_image ffmpeg -version >/dev/null || fail "ffmpeg"
in_image ffprobe -version >/dev/null || fail "ffprobe"
in_image aria2c --version >/dev/null || fail "aria2c"
in_image deno --version >/dev/null || fail "deno"
pass "tools: yt-dlp, ffmpeg, ffprobe, aria2c, deno"

# --- no-legacy: nothing local-only in the image -------------------------------
in_image sh -c 'test ! -e /app/legacy' || fail "/app/legacy exists in the image"
found="$(in_image sh -c 'find / -xdev -name cookies.txt 2>/dev/null' || true)"
[ -z "$found" ] || fail "cookies.txt found in the image: $found"
pass "no-legacy: no /app/legacy, no cookies.txt"

# --- smoke: container up, /healthz 200 within 60s -------------------------------
smoke="$RUN_ID-smoke"
CONTAINERS+=("$smoke")
docker run -d --platform linux/amd64 --name "$smoke" -p "$PORT:8000" "$IMAGE" >/dev/null
wait_healthy "$smoke" "$PORT" || fail "smoke: /healthz not 200 within 60s"
body="$(curl -fsS "http://localhost:$PORT/healthz")"
echo "$body" | grep -q '"status":"ok"' || fail "smoke: unexpected body $body"
pass "smoke: /healthz -> $body"

# --- cli: `fetcharr` is on PATH and reaches the DB as the app user ------------------
set +e
cli_out="$(docker exec "$smoke" fetcharr reset-password </dev/null 2>&1)"
cli_code=$?
set -e
[ "$cli_code" = "1" ] || fail "cli: expected exit 1 on a fresh DB, got $cli_code: $cli_out"
echo "$cli_out" | grep -q "No account yet" || fail "cli: unexpected output: $cli_out"
pass "cli: fetcharr reset-password reports no account on a fresh DB"
docker rm -f "$smoke" >/dev/null

# --- puid: PUID/PGID own /config/fetcharr.db and run uvicorn --------------------------
puid="$RUN_ID-puid"
CONTAINERS+=("$puid")
docker run -d --platform linux/amd64 --name "$puid" -e PUID=1234 -e PGID=1234 \
  -p "$PORT:8000" "$IMAGE" >/dev/null
wait_healthy "$puid" "$PORT" || fail "puid: container did not become healthy"
owner="$(docker exec "$puid" stat -c %u:%g /config/fetcharr.db)"
[ "$owner" = "1234:1234" ] || fail "puid: /config/fetcharr.db owned by $owner"
app_uid="$(docker exec "$puid" id -u app)"
uvicorn_uid="$(docker exec "$puid" sh -c '
  for d in /proc/[0-9]*; do
    [ "$d" = "/proc/$$" ] && continue  # this shell'"'"'s own cmdline contains the pattern
    if tr "\0" " " < "$d/cmdline" 2>/dev/null | grep -q "uvicorn app.main:app"; then
      awk "/^Uid:/ {print \$2}" "$d/status"; break
    fi
  done')"
[ "$app_uid" = "1234" ] || fail "puid: id -u app is $app_uid"
[ "$uvicorn_uid" = "1234" ] || fail "puid: uvicorn runs as uid '$uvicorn_uid'"
pass "puid: db owned by $owner, uvicorn uid $uvicorn_uid"
docker rm -f "$puid" >/dev/null

# --- backup: existing DB is backed up before migrating, newest 5 kept ---------------
vol="$RUN_ID-config"
VOLUMES+=("$vol")
in_seed() { docker run --rm --platform linux/amd64 -v "$vol:/config" --entrypoint "" "$IMAGE" "$@"; }
in_seed sh -c '
  mkdir -p /config/backups
  python -c "import sqlite3; sqlite3.connect(\"/config/fetcharr.db\").execute(\"CREATE TABLE seed (x)\")"
  for i in 1 2 3 4 5 6; do echo old > /config/backups/fetcharr-premigrate-2020010${i}T000000000000Z.db; done
  chown -R 1000:1000 /config'
backup="$RUN_ID-backup"
CONTAINERS+=("$backup")
docker run -d --platform linux/amd64 --name "$backup" -v "$vol:/config" -p "$PORT:8000" "$IMAGE" >/dev/null
wait_healthy "$backup" "$PORT" || fail "backup: container did not become healthy"
listing="$(docker exec "$backup" sh -c 'ls /config/backups')"
count="$(echo "$listing" | grep -c '^fetcharr-premigrate-')"
[ "$count" = "5" ] || fail "backup: expected 5 backups, got $count: $listing"
newest="$(echo "$listing" | sort | tail -1)"
case "$newest" in fetcharr-premigrate-2020*) fail "backup: no new backup created: $listing" ;; esac
docker exec "$backup" python -c "
import sqlite3, sys
names = [r[0] for r in sqlite3.connect('/config/backups/$newest').execute(\"SELECT name FROM sqlite_master\")]
sys.exit(0 if 'seed' in names else 1)" || fail "backup: newest backup lacks the seeded table"
pass "backup: 5 kept, newest $newest"

echo "all image checks passed"
