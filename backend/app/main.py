from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse

from app.auth import router as auth_router
from app.auth.dependencies import check_origin, require_auth
from app.auth.utils import LoginRateLimiter
from app.config import Settings
from app.db.session import Database
from app.inspections import router as inspections_router

STATIC_DIR = Path("/app/static")


def create_app(settings: Settings | None = None, static_dir: Path = STATIC_DIR) -> FastAPI:
    settings = settings or Settings()
    static_root = static_dir.resolve()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.db = Database(settings.database_url)
        try:
            yield
        finally:
            await app.state.db.dispose()

    app = FastAPI(title="fetcharr", version=settings.app_version, lifespan=lifespan)
    app.state.settings = settings
    app.state.login_limiter = LoginRateLimiter()

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": settings.app_version}

    # Every /api route requires a session or the API key, except the public auth routes.
    app.include_router(auth_router.public, dependencies=[Depends(check_origin)])
    app.include_router(auth_router.protected, dependencies=[Depends(require_auth)])
    app.include_router(inspections_router.router, dependencies=[Depends(require_auth)])

    @app.api_route(
        "/api/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        dependencies=[Depends(require_auth)],
    )
    async def api_not_found(path: str) -> None:
        raise HTTPException(status_code=404, detail="Not Found")

    # Sync on purpose: FastAPI runs it in a worker thread, keeping the filesystem
    # checks off the event loop (requirements §3.2).
    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        candidate = (static_root / path).resolve()
        if path and candidate.is_relative_to(static_root) and candidate.is_file():
            return FileResponse(candidate)
        index = static_root / "index.html"
        if not index.is_file():
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(index)

    return app


app = create_app()
