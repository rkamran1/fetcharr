"""What the status page needs; the path self-test itself runs once, at startup (§7.6)."""

from dataclasses import asdict

from app.system.schemas import PathReportRead, SystemStatus
from app.system.utils import PathReport


class SystemService:
    def __init__(self, version: str, paths: PathReport) -> None:
        self.version = version
        self.paths = paths

    def status(self) -> SystemStatus:
        return SystemStatus(version=self.version, paths=PathReportRead(**asdict(self.paths)))
