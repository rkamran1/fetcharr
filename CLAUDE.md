# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

**fetcharr**: a Dockerised FastAPI + React app that wraps the `yt-dlp` CLI, organises downloads in Sonarr/Radarr layout and asks Radarr/Sonarr to import them.

- `backend/`: Python 3.13, FastAPI, SQLAlchemy 2 async + aiosqlite, Alembic, pydantic-settings, `uv`.
- `frontend/`: React + Vite + TypeScript + Tailwind + shadcn/ui + TanStack Query, `npm`.
- `Dockerfile`, `docker/entrypoint.sh`, `scripts/test-image.sh`: the single `linux/amd64` image and its checks.
- `.github/workflows/docker.yml`: CI (backend, frontend, image). Docker Hub push is gated by the repo variable `DOCKERHUB_PUSH_ENABLED`.

## Where the rest lives (local only, git-ignored)

- `.claude/requirements/inital_requirements.md`: product requirements and architecture (the § references below). For the backend layout, the **Backend structure** section below is the source of truth; §14 follows it.
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

## Backend structure

Code is grouped by feature, not by technical layer. `backend/tests/repo/test_structure.py` enforces these rules by parsing the source.

```
backend/app/
├── main.py            # create_app: lifespan, include each domain's router, SPA
├── config.py          # Settings
├── cli.py             # fetcharr reset-password, through AuthService
├── db/                # shared infrastructure, no domain code
│   ├── base.py        # Base, utcnow()
│   ├── registry.py    # imports every domain's models.py (Alembic metadata)
│   ├── session.py     # Database: PRAGMAs, read sessions, the single writer
│   ├── backup.py
│   └── migrations/
├── auth/              # domain: router, schemas, service, models, dependencies, exceptions, utils
├── inspections/       # domain: router, schemas, service, models, dependencies, exceptions, utils
├── requests/          # domain: a download request and the jobs it creates
├── jobs/              # domain: + pipeline.py (the four steps) and manager.py (the JobManager)
├── events/            # domain: the in-memory EventHub and the /api/events SSE stream
├── system/            # domain: the startup path self-test and /api/system/status
├── settings/          # domain: the settings store, the Fernet helpers (utils.py) and /api/settings
├── arr/               # domain: /api/arr/radarr/* (the connection test and the movie picker)
├── ytdlp/             # library: schemas (DownloadOptions), command, formats, stream, runtime, inspect, runner
├── integrations/      # library: arr.py (the Radarr client, its movie cache and the import lock)
└── library/           # library: naming, organizer, probe
```

- **Domain package:** a folder under `backend/app/` for one feature. Allowed files: `router.py`, `schemas.py`, `service.py`, `models.py`, `dependencies.py`, `exceptions.py`, `constants.py`, `utils.py`. Create only the files the domain needs. Any other module name needs a line here first.
- **Extra modules, by exception:** `jobs/` also has `pipeline.py` (the four checkpointed steps of §6.1) and `manager.py` (the `JobManager`: claim loop, recovery, concurrency, throttled writes). They are listed in `EXTRA_MODULES` in `test_structure.py`; nothing else may add a module name without a line here.
- **Library package** (`ytdlp/`, `library/`, `integrations/`, later `transcode/`): no endpoints and no FastAPI imports. Same file names where they apply (`schemas.py` for Pydantic models, `utils.py` for pure helpers); otherwise modules named after what they wrap (`command.py`, `probe.py`). A new library package is added to `LIBRARY_PACKAGES` in `test_structure.py` and to this list; every other package under `app/` (except `db/`) counts as a domain.
- **`router.py`:** HTTP only. Parse the request (via schemas), call one service method, map domain exceptions to HTTP responses. Never imports `sqlalchemy`, `app.db`, `asyncio.subprocess` or another domain's `service`. Routers are included in `main.py` with `dependencies=[Depends(require_auth)]` unless public by design.
- **`schemas.py`:** every Pydantic `BaseModel` lives in a `schemas.py`. The only exception is `Settings` in `config.py`.
- **`service.py`:** one service class per domain (`<Domain>Service`), constructed with its dependencies (`Database`, `Settings`, other services). A `get_<domain>_service` dependency in `dependencies.py` builds it per request. The two exceptions are the long-lived `JobManager` (`app.state.manager`), `EventHub` (`app.state.hub`) and `RadarrClient` (`app.state.radarr`, a library object), created in the lifespan because they own the running jobs, the in-memory progress and the one connection pool, movie cache and import lock (§6.1, §3.1 rule 5); request-scoped services take them as constructor arguments. It holds the business logic, all DB access (through `Database.read_session()` / `write_session()`, §3.1) and calls into libraries. It never imports `fastapi` and never raises `HTTPException`: it raises the domain's exceptions.
- **`models.py`:** the domain's SQLAlchemy models, on `app.db.base.Base`. Every models module is imported in `app/db/registry.py`. Moving a model between modules is not a schema change; `alembic check` must stay clean.
- **`exceptions.py`:** domain errors carry what the router needs (e.g. status, message, `needs_cookies`); the router maps them. Libraries raise their own errors (e.g. `ytdlp.inspect.YtdlpError(kind, message)`), which the service maps to domain errors.
- **`utils.py`:** pure functions and small helpers; no DB, no HTTP. Blocking helpers are called through `asyncio.to_thread` by the service.
- **Imports:** routers → own service/schemas/dependencies; services → own models/schemas/exceptions/utils, libraries, other services; libraries → other libraries only. No cycles, no library importing a domain.
- **Tests mirror the app:** `tests/<domain>/test_router.py` (HTTP, including the 401 case), `tests/<domain>/test_service.py`, `tests/<domain>/test_utils.py`, and `tests/<library>/…`. Shared fixtures (`app`, `client`, `settings`, `migrated_db_url`, `fake_ytdlp`) live in `tests/conftest.py`.

## Frontend structure

Code is grouped by feature, mirroring the backend. `frontend/eslint.structure.test.ts` keeps the import rule honest.

```
frontend/src/
├── api/client.ts      # only request() and ApiError
├── App.tsx            # routes
├── components/
│   ├── AppShell.tsx   # shared chrome
│   └── ui/            # shadcn only
├── lib/               # shared helpers (queryClient, utils, passwords)
├── pages/HomePage.tsx # not one feature's
├── test/              # the test harness (mockApi, setup)
└── features/<domain>/ # auth, settings, inspections, system, requests, jobs
    ├── api.ts         # that domain's request functions and query keys
    ├── types.ts       # its API types
    ├── components/, pages/, and colocated *.test.tsx
    └── index.ts       # what other features may use
```

- **Import rule:** another feature is imported only through its index (`@/features/<name>`); inside a feature, use relative paths. ESLint's `no-restricted-imports` bans `@/features/*/*`.
- **Shared code** is `src/api/client.ts`, `src/components/ui/`, `src/components/AppShell.tsx`, `src/lib/` and `src/test/`. Everything else belongs to a feature.
- A new feature is a new folder with an `index.ts`; no registration anywhere else.

## Conventions

- **SQLite (§3.1):** PRAGMAs on every connection (`app/db/session.py`). Every write goes through `Database.write_session()` (one lock, one writer connection, `BEGIN IMMEDIATE`). Keep write transactions short and never hold one across a subprocess, network call or other slow `await`.
- **Async (§3.2):** never block the event loop. Blocking file I/O, hashing and directory scans go through `asyncio.to_thread` (or a sync FastAPI handler). No `time.sleep`, `requests`, sync `httpx.Client`, `subprocess.run`/`Popen` or sync DB sessions in async code. Ruff's `ASYNC` rules enforce it; fix violations, never suppress them. Tests run with asyncio debug mode and fail on any callback over 100 ms (`backend/tests/loop_guard.py`); one-off construction inside an async fixture (building the app, migrating the database) gets a 1 s budget instead, because that is startup work rather than the app blocking its own loop.
- **Pipeline (§6.1):** a single process (`uvicorn --workers 1`, set in the entrypoint), four checkpointed steps, each safe to re-run. No workflow engine or task-queue library.
- **Retries:** only `tenacity.AsyncRetrying` with explicit retryable exception types and `reraise=True`. No hand-written retry loops. Tests use `wait_none()`.
- **Subprocesses:** yt-dlp/ffmpeg always as argv lists (`asyncio.create_subprocess_exec`), never a shell. Only allow-listed yt-dlp options.
- **Files:** work in `incomplete/<job_id>/`, then an atomic move to `completed/`. Final paths are resolved and checked to stay inside their root.
- **Secrets:** cookies and arr API keys are Fernet-encrypted at rest with the key from `SECRET_KEY`/`SECRET_KEY_FILE` (loaded once in the lifespan onto `app.state.secret_key`), never returned by the API, never logged.
- **Endpoints:** every non-public endpoint requires a session. Each endpoint has a test, including the unauthenticated `401` case.
- **Migrations:** each model change gets an Alembic revision (`backend/app/db/migrations/versions/`). Applied revisions are never edited.
- **Config:** each env var is in `backend/app/config.py`, `docker-compose.example.yml` and the README env table.
- **Tests never touch the internet**, real `/web-downloads` or real Radarr/Sonarr. Use `respx`, a local HTTP server and `tmp_path`. Real-site tests are marked `@pytest.mark.network` and excluded by default.
