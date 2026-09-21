# fetcharr

A self-hosted web UI for `yt-dlp` that downloads into Sonarr/Radarr's folder layout and asks them to import the result.

Status: early development. This version has the skeleton (`/healthz`, the database foundation, the Docker image) and login for a single account.

## Run it

Add the service from [`docker-compose.example.yml`](docker-compose.example.yml) to the compose file that runs your arr stack, then:

```bash
docker compose pull fetcharr && docker compose up -d fetcharr
```

On start the container backs up an existing database to `/config/backups/` (keeping the newest 5), applies migrations, and serves the UI on port 8000 inside the container.

On the first visit, fetcharr asks you to create its one account. Settings has "Change password" and an API key (sent as the `X-Api-Key` header).

### Password reset

If you forget the password, reset it inside the container. This signs out every session:

```bash
docker exec -it fetcharr fetcharr reset-password
```

## Configuration

Mount two volumes: `/config` (database and backups, on a local disk) and `/web-downloads`, which holds `completed/` and `incomplete/`. Mount the same host downloads folder at `/web-downloads` in Radarr and Sonarr as well: fetcharr tells them to import from paths under `/web-downloads`, so those paths must exist inside their containers too. Keeping both folders on one volume makes the move from `incomplete/` to `completed/` an instant rename.

| Variable | Default | Used by | Meaning |
|---|---|---|---|
| `PUID` | `1000` | entrypoint | uid the app runs as. Use the same as your Sonarr/Radarr. |
| `PGID` | `1000` | entrypoint | gid the app runs as. |
| `UMASK` | `022` | entrypoint | umask for files the app creates (`002` to match a shared arr group). |
| `TZ` | unset | container | time zone, e.g. `Asia/Karachi`. |
| `DATABASE_URL` | `sqlite+aiosqlite:////config/fetcharr.db` | app | database location. Keep `/config` on a local disk. |
| `COOKIE_SECURE` | `false` | app | add `Secure` to the session cookie. Keep `false` for plain HTTP on the LAN, set `true` behind HTTPS. |
| `COMPLETED_DIR` | `/web-downloads/completed` | app | finished downloads, in `movies/`, `tv-shows/` and `other/`, waiting for Radarr/Sonarr to import them. |
| `INCOMPLETE_DIR` | `/web-downloads/incomplete` | app | per-job work folders; replaced files go to `_replaced/`. Keep it on the same volume as `COMPLETED_DIR`. |
| `MAX_CONCURRENT_DOWNLOADS` | `2` | app | how many downloads run at once. The slot is held only while yt-dlp runs. |
| `MAX_CONCURRENT_TRANSCODES` | `1` | app | how many transcodes run at once. The slot is held only while ffmpeg runs, so downloads keep flowing behind it. |
| `LIBVA_DRIVER_NAME` | `iHD` | app | which libva driver ffmpeg loads for QSV/VAAPI. `iHD` is the Intel one; it only matters when `/dev/dri` is passed through. |
| `AUTO_RESUME` | `true` | app | after a restart, resume jobs from their last completed step. `false` marks them failed instead, to be retried by hand. |
| `SECRET_KEY` | unset | app | the Fernet key that encrypts secrets at rest (arr API keys, later cookies). Unset, fetcharr generates `SECRET_KEY_FILE` on first start. |
| `SECRET_KEY_FILE` | `/config/secret.key` | app | where that key is read from, and written (mode `0600`) when it doesn't exist yet. Keep `/config` backed up: a lost key means re-entering every stored secret. |
| `RADARR_URL` | unset | app | Radarr's base URL, e.g. `http://radarr:7878`. Set here it overrides what Settings holds. |
| `RADARR_API_KEY` | unset | app | Radarr's API key. Set here it overrides what Settings holds and is never written to the database. |
| `SONARR_URL` | unset | app | Sonarr's base URL, e.g. `http://sonarr:8989`. Set here it overrides what Settings holds. |
| `SONARR_API_KEY` | unset | app | Sonarr's API key. Set here it overrides what Settings holds and is never written to the database. |
| `APP_VERSION` | `dev` | app | version shown in the UI and `/healthz`. Set by the image build (`--build-arg APP_VERSION=…`). |

## Development

Requirements: `uv`, Node 22, Docker (with `buildx`).

```bash
# backend
uv sync --directory backend
uv run --directory backend pytest -q

# run it on the host: /web-downloads only exists in the container, so point the
# download folders somewhere writable first
export COMPLETED_DIR=./.local/completed INCOMPLETE_DIR=./.local/incomplete
export DATABASE_URL=sqlite+aiosqlite:///./.local/fetcharr.db
uv run --directory backend uvicorn app.main:app --reload

# frontend
npm --prefix frontend ci
npm --prefix frontend run dev        # proxies /healthz and /api to http://localhost:8000

# everything in containers, with hot reload, on http://localhost:8686
docker compose -f docker-compose.dev.yml up --build
```

The dev stack writes downloads to `./.local/web-downloads` (git-ignored), so finished files land in `./.local/web-downloads/completed/other/`.

### Testing the Radarr import locally

`docker-compose.dev.yml` also runs a throwaway **Radarr** (http://localhost:7878) and **Sonarr** (http://localhost:8989), so the import can be tested without deploying to a homelab. All three containers mount `./.local/web-downloads` at `/web-downloads`, which is the point: the path fetcharr hands Radarr in a `DownloadedMoviesScan` means the same file inside Radarr, so `Move` is a rename rather than a copy (§7.1, §7.5).

Their API keys are seeded from the compose file, so fetcharr can reach Radarr on a fresh volume with nothing copied by hand. Override them (and `TZ`) with a `.env` beside the compose file if you like:

```bash
DEV_RADARR_API_KEY=0123456789abcdef0123456789abcdef   # the default, shown
DEV_SONARR_API_KEY=fedcba9876543210fedcba9876543210   # the default, shown
```

Both arr apps run with `AUTH__METHOD=External`, i.e. no login screen. That is fine for a container bound to localhost and is **not** how to run them anywhere else.

#### Library folders and the one-time arr setup

Radarr imports *out of* `completed/` and *into* its own root folder, and fetcharr never writes into that root folder (§7.1). The root folder therefore has to be a different directory on the **same mount**, or the `Move` becomes a copy + delete. In this stack that is `/web-downloads/library/`, a sibling of `completed/` and `incomplete/`:

```
.local/web-downloads/
├── incomplete/          fetcharr works here
├── completed/           fetcharr writes finished files here
│   ├── movies/            → Radarr imports FROM here
│   ├── tv-shows/          → Sonarr imports FROM here
│   └── other/
└── library/             → the arr apps import INTO here (fetcharr never touches it)
    ├── movies/
    └── tv-shows/
```

`.local/` is git-ignored, so after a fresh clone or a `docker compose down -v` run this once:

```bash
RK=0123456789abcdef0123456789abcdef   # DEV_RADARR_API_KEY
SK=fedcba9876543210fedcba9876543210   # DEV_SONARR_API_KEY

mkdir -p .local/web-downloads/library/movies .local/web-downloads/library/tv-shows

curl -s -X POST http://localhost:7878/api/v3/rootfolder -H "X-Api-Key: $RK" \
  -H 'Content-Type: application/json' -d '{"path":"/web-downloads/library/movies"}'
curl -s -X POST http://localhost:8989/api/v3/rootfolder -H "X-Api-Key: $SK" \
  -H 'Content-Type: application/json' -d '{"path":"/web-downloads/library/tv-shows"}'
```

Then give Radarr a movie to be missing. Radarr only knows TMDB titles, so look one up and add it monitored, **without** searching for a release:

```bash
curl -s -H "X-Api-Key: $RK" "http://localhost:7878/api/v3/movie/lookup?term=Big+Buck+Bunny"
curl -s -X POST http://localhost:7878/api/v3/movie -H "X-Api-Key: $RK" \
  -H 'Content-Type: application/json' -d '{
    "tmdbId": 10378, "title": "Big Buck Bunny", "year": 2008,
    "qualityProfileId": 4, "rootFolderPath": "/web-downloads/library/movies",
    "monitored": true, "minimumAvailability": "released",
    "addOptions": {"searchForMovie": false}
  }'
```

Monitored with no file is exactly what "missing" means, so it now shows up in fetcharr under **Download Movie → Missing in Radarr**. Pick it, paste a URL, and the job should reach `imported` with the file under `library/movies/`.

fetcharr has no Sonarr client yet, so Sonarr just holds a root folder on the shared volume until M6.

`VITE_PROXY_TARGET` (dev only, default `http://localhost:8000`) sets where the Vite dev server proxies `/healthz` and `/api`.

The image targets `linux/amd64` only. On Apple Silicon always build with `docker buildx build --platform linux/amd64 -t fetcharr:dev --load .`, then check it with `scripts/test-image.sh fetcharr:dev`.

All check commands are listed in [`CLAUDE.md`](CLAUDE.md).
