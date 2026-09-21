"""System status (requirements §11): the app version, the path self-test and the iGPU."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.system.dependencies import get_system_service
from app.system.schemas import SystemStatus, TranscodeReportRead
from app.system.service import SystemService

router = APIRouter(prefix="/api/system", tags=["system"])

Service = Annotated[SystemService, Depends(get_system_service)]


@router.get("/status", response_model=SystemStatus)
async def status(service: Service) -> SystemStatus:
    return service.status()


@router.post("/transcode-test", response_model=TranscodeReportRead)
async def transcode_test(service: Service) -> TranscodeReportRead:
    return await service.test_hardware()
