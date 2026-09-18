# fetcharr

A self-hosted web UI for `yt-dlp` that downloads into Sonarr/Radarr's folder layout and asks them to import the result.

Status: early development. This version is the skeleton: a page that shows the app version, `/healthz`, the database foundation and the Docker image.

## Run it

Add the service from [`docker-compose.example.yml`](docker-compose.example.yml) to the compose file that runs your arr stack, then:

```bash
docker compose pull fetcharr && docker compose up -d fetcharr
```

On start the container backs up an existing database to `/config/backups/` (keeping the newest 5), applies migrations, and serves the UI on port 8000 inside the container.

## Configuration

| Variable | Default | Used by | Meaning |
|---|---|---|---|
| `PUID` | `1000` | entrypoint | uid the app runs as. Use the same as your Sonarr/Radarr. |
| `PGID` | `1000` | entrypoint | gid the app runs as. |
| `UMASK` | `022` | entrypoint | umask for files the app creates (`002` to match a shared arr group). |
| `TZ` | unset | container | time zone, e.g. `Asia/Karachi`. |
| `DATABASE_URL` | `sqlite+aiosqlite:////config/fetcharr.db` | app | database location. Keep `/config` on a local disk. |
| `APP_VERSION` | `dev` | app | version shown in the UI and `/healthz`. Set by the image build (`--build-arg APP_VERSION=…`). |

## Development

Requirements: `uv`, Node 22, Docker (with `buildx`).

```bash
# backend
uv sync --directory backend
uv run --directory backend pytest -q

# frontend
npm --prefix frontend ci
npm --prefix frontend run dev        # proxies /healthz and /api to http://localhost:8000

# everything in containers, with hot reload, on http://localhost:8686
docker compose -f docker-compose.dev.yml up --build
```

`VITE_PROXY_TARGET` (dev only, default `http://localhost:8000`) sets where the Vite dev server proxies `/healthz` and `/api`.

The image targets `linux/amd64` only. On Apple Silicon always build with `docker buildx build --platform linux/amd64 -t fetcharr:dev --load .`, then check it with `scripts/test-image.sh fetcharr:dev`.

All check commands are listed in [`CLAUDE.md`](CLAUDE.md).
