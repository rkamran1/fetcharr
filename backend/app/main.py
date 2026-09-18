from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from app.config import Settings
from app.db.session import Database

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

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": settings.app_version}

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
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
