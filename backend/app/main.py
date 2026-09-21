import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse

from app.arr import router as arr_router
from app.auth import router as auth_router
from app.auth.dependencies import check_origin, require_auth
from app.auth.utils import LoginRateLimiter
from app.config import Settings
from app.db.session import Database
from app.events import router as events_router
from app.events.service import EventHub
from app.inspections import router as inspections_router
from app.integrations.arr import RadarrClient, SonarrClient
from app.jobs import router as jobs_router
from app.jobs.manager import JobManager
from app.requests import router as requests_router
from app.settings import router as settings_router
from app.settings.service import SettingsService
from app.settings.utils import load_secret_key
from app.sites import router as sites_router
from app.sites.service import SitesService
from app.system import router as system_router
from app.system.utils import PathReport, check_paths
from app.transcode.hwcheck import HardwareStatus

STATIC_DIR = Path("/app/static")
logger = logging.getLogger("fetcharr")


def create_app(settings: Settings | None = None, static_dir: Path = STATIC_DIR) -> FastAPI:
    settings = settings or Settings()
    static_root = static_dir.resolve()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.db = Database(settings.database_url)
        app.state.hub = EventHub()
        # Reading or generating the key file is blocking, and happens once (§3.2, §8).
        app.state.secret_key = await asyncio.to_thread(
            load_secret_key, settings.secret_key, settings.secret_key_file
        )
        # Many filesystem calls, so off the event loop (§3.2, §7.6).
        app.state.path_report = await asyncio.to_thread(
            check_paths, settings.completed_dir, settings.incomplete_dir
        )
        _warn_about_paths(app.state.path_report)
        # Startup only stats the render device; the encode test runs from Settings (§13.1).
        app.state.hardware = HardwareStatus(driver=settings.libva_driver_name)
        await app.state.hardware.start()
        # Long-lived like the hub and the manager: one connection pool, one library
        # cache and one import lock per arr app for the whole process (§6.1).
        app.state.radarr = RadarrClient()
        app.state.sonarr = SonarrClient()
        app.state.manager = JobManager(
            app.state.db,
            settings,
            app.state.hub,
            SettingsService(app.state.db, settings, app.state.secret_key),
            app.state.radarr,
            app.state.sonarr,
            SitesService(app.state.db, app.state.secret_key),
        )
        await app.state.manager.start()
        try:
            yield
        finally:
            await app.state.manager.stop()
            await app.state.radarr.aclose()
            await app.state.sonarr.aclose()
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
    app.include_router(requests_router.router, dependencies=[Depends(require_auth)])
    app.include_router(jobs_router.router, dependencies=[Depends(require_auth)])
    app.include_router(events_router.router, dependencies=[Depends(require_auth)])
    app.include_router(system_router.router, dependencies=[Depends(require_auth)])
    app.include_router(settings_router.router, dependencies=[Depends(require_auth)])
    app.include_router(arr_router.router, dependencies=[Depends(require_auth)])
    app.include_router(sites_router.router, dependencies=[Depends(require_auth)])

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


def _warn_about_paths(report: PathReport) -> None:
    """A failing self-test isn't fatal (§7.6), but it must not be a mystery in the logs."""
    for check in report.checks:
        if not check.ok:
            logger.warning(
                "path self-test failed for %s: %s. Mount the downloads volume, or set "
                "COMPLETED_DIR and INCOMPLETE_DIR to a folder fetcharr can write to.",
                check.path,
                check.error,
            )
    if report.ok is False and report.same_filesystem is False:
        logger.warning(
            "COMPLETED_DIR and INCOMPLETE_DIR are on different filesystems, so finishing a "
            "download copies instead of renaming it. Keep both on one volume."
        )


app = create_app()
