"""What the status page needs; the path self-test itself runs once, at startup (§7.6)."""

from dataclasses import asdict

from app.system.schemas import PathReportRead, SystemStatus, TranscodeReportRead
from app.system.utils import PathReport
from app.transcode.hwcheck import HardwareStatus


class SystemService:
    def __init__(self, version: str, paths: PathReport, hardware: HardwareStatus) -> None:
        self.version = version
        self.paths = paths
        self.hardware = hardware

    def status(self) -> SystemStatus:
        return SystemStatus(
            version=self.version,
            paths=PathReportRead(**asdict(self.paths)),
            transcode=TranscodeReportRead(**asdict(self.hardware.report)),
        )

    async def test_hardware(self) -> TranscodeReportRead:
        """What the Settings button runs: vainfo plus a one-second encode per profile."""
        return TranscodeReportRead(**asdict(await self.hardware.refresh()))
