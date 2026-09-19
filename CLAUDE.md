# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

**fetcharr**: a Dockerised FastAPI + React app that wraps the `yt-dlp` CLI, organises downloads in Sonarr/Radarr layout and asks Radarr/Sonarr to import them.

- `backend/`: Python 3.13, FastAPI, SQLAlchemy 2 async + aiosqlite, Alembic, pydantic-settings, `uv`.
- `frontend/`: React + Vite + TypeScript + Tailwind + shadcn/ui + TanStack Query, `npm`.
- `Dockerfile`, `docker/entrypoint.sh`, `scripts/test-image.sh`: the single `linux/amd64` image and its checks.
- `.github/workflows/docker.yml`: CI (backend, frontend, image). Docker Hub push is gated by the repo variable `DOCKERHUB_PUSH_ENABLED`.

## Where the rest lives (local only, git-ignored)

- `.claude/requirements/inital_requirements.md`: product requirements and architecture (the § references below).
- `.claude/plans/<ID>-<slug>.md`: one plan per milestone, implemented with `/dev-workflow-loop <ID>`.
- `.claude/documentations/`: cached library docs.
- `legacy/`: the old `download_video.sh` (behavioural reference for the command builder), its `cookies.txt` (live secrets) and old guide. **Read-only, never committed, absent in CI and the Docker build context. No test or build step may read it.**

## Verification commands

Run from the repo root.

| Check | Command |
|---|---|
| Backend lint | `uv run --directory backend ruff check .` |
| Backend format | `uv run --directory backend ruff format --check .` |
| Backend types | `uv run --directory backend ty check app` |
| Backend tests | `uv run --directory backend pytest -q` |
| Migrations | `D=$(mktemp -d); DATABASE_URL=sqlite+aiosqlite:///$D/t.db uv run --directory backend alembic upgrade head && DATABASE_URL=sqlite+aiosqlite:///$D/t.db uv run --directory backend alembic check` |
| Frontend lint | `npm --prefix frontend run lint` |
| Frontend types | `npm --prefix frontend run typecheck` |
| Frontend tests | `npm --prefix frontend test -- --run` |
| Frontend build | `npm --prefix frontend run build` |
| Image build | `docker buildx build --platform linux/amd64 -t fetcharr:dev --load .` |
| Image smoke | `docker run -d --rm --name fetcharr-smoke -p 18000:8000 fetcharr:dev`, poll `curl -fsS http://localhost:18000/healthz` for up to 60s, then `docker stop fetcharr-smoke` |
| Image checks (tools, smoke, PUID/PGID, backups, no local files) | `scripts/test-image.sh fetcharr:dev` |

`alembic check` needs a database already at head, and the default `DATABASE_URL` points at `/config` (container only), so the migrations check runs both commands against one temporary database.

## Conventions

- **SQLite (§3.1):** PRAGMAs on every connection (`app/db/session.py`). Every write goes through `Database.write_session()` (one lock, one writer connection, `BEGIN IMMEDIATE`). Keep write transactions short and never hold one across a subprocess, network call or other slow `await`.
- **Async (§3.2):** never block the event loop. Blocking file I/O, hashing and directory scans go through `asyncio.to_thread` (or a sync FastAPI handler). No `time.sleep`, `requests`, sync `httpx.Client`, `subprocess.run`/`Popen` or sync DB sessions in async code. Ruff's `ASYNC` rules enforce it; fix violations, never suppress them. Tests run with asyncio debug mode and fail on any callback over 100 ms (`backend/tests/loop_guard.py`).
- **Pipeline (§6.1):** a single process (`uvicorn --workers 1`, set in the entrypoint), four checkpointed steps, each safe to re-run. No workflow engine or task-queue library.
- **Retries:** only `tenacity.AsyncRetrying` with explicit retryable exception types and `reraise=True`. No hand-written retry loops. Tests use `wait_none()`.
- **Subprocesses:** yt-dlp/ffmpeg always as argv lists (`asyncio.create_subprocess_exec`), never a shell. Only allow-listed yt-dlp options.
- **Files:** work in `incomplete/<job_id>/`, then an atomic move to `completed/`. Final paths are resolved and checked to stay inside their root.
- **Secrets:** cookies and arr API keys are encrypted at rest, never returned by the API, never logged.
- **Endpoints:** every non-public endpoint requires a session. Each endpoint has a test, including the unauthenticated `401` case.
- **Migrations:** each model change gets an Alembic revision (`backend/app/db/migrations/versions/`). Applied revisions are never edited.
- **Config:** each env var is in `backend/app/config.py`, `docker-compose.example.yml` and the README env table.
- **Tests never touch the internet**, real `/web-downloads` or real Radarr/Sonarr. Use `respx`, a local HTTP server and `tmp_path`. Real-site tests are marked `@pytest.mark.network` and excluded by default.
