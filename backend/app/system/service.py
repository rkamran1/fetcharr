"""The full status report (requirements §11): versions, paths, iGPU, database, arr."""

import asyncio
from dataclasses import asdict

from app.arr.schemas import ArrTestResult
from app.arr.service import ArrService
from app.config import Settings
from app.db.backup import backups_dir
from app.jobs.manager import JobManager
from app.settings.service import SettingsService
from app.system.schemas import (
    ArrStatusRead,
    ConcurrencyRead,
    DatabaseRead,
    PathReportRead,
    SystemStatus,
    ToolsRead,
    TranscodeReportRead,
)
from app.system.utils import check_paths, database_report
from app.transcode.hwcheck import HardwareStatus
from app.ytdlp.runtime import tool_versions


class SystemService:
    def __init__(
        self,
        settings: Settings,
        hardware: HardwareStatus,
        manager: JobManager,
        arr: ArrService,
        stored: SettingsService,
    ) -> None:
        self.settings = settings
        self.hardware = hardware
        self.manager = manager
        self.arr = arr
        self.stored = stored

    async def status(self) -> SystemStatus:
        """Everything the Status page shows; a down arr is a field, never a failed report."""
        async with asyncio.TaskGroup() as group:
            versions = group.create_task(tool_versions())
            paths = group.create_task(
                asyncio.to_thread(
                    check_paths, self.settings.completed_dir, self.settings.incomplete_dir
                )
            )
            database = group.create_task(
                asyncio.to_thread(
                    database_report,
                    self.settings.database_url,
                    backups_dir(self.settings.database_url),
                )
            )
            radarr = group.create_task(self.arr.test())
            sonarr = group.create_task(self.arr.test_sonarr())
            radarr_set = group.create_task(self.stored.radarr())
            sonarr_set = group.create_task(self.stored.sonarr())
        return SystemStatus(
            version=self.settings.app_version,
            tools=ToolsRead(
                ytdlp=versions.result().ytdlp,
                ffmpeg=versions.result().ffmpeg,
                deno=versions.result().deno,
                js_runtime=self.manager.js_runtime,
                aria2c=self.manager.aria2c_available,
                update_on_start=self.settings.ytdlp_update_on_start,
            ),
            paths=PathReportRead(**asdict(paths.result())),
            transcode=TranscodeReportRead(**asdict(self.hardware.report)),
            database=DatabaseRead(**asdict(database.result())),
            concurrency=ConcurrencyRead(
                downloads=self.settings.max_concurrent_downloads,
                transcodes=self.settings.max_concurrent_transcodes,
            ),
            radarr=_arr(radarr_set.result() is not None, radarr.result()),
            sonarr=_arr(sonarr_set.result() is not None, sonarr.result()),
        )

    async def test_hardware(self) -> TranscodeReportRead:
        """What the Settings button runs: vainfo plus a one-second encode per profile."""
        return TranscodeReportRead(**asdict(await self.hardware.refresh()))


def _arr(configured: bool, result: ArrTestResult) -> ArrStatusRead:
    return ArrStatusRead(
        configured=configured, ok=result.ok, version=result.version, error=result.error
    )
