"""System status (requirements §11): the app version and the startup path self-test."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.system.dependencies import get_system_service
from app.system.schemas import SystemStatus
from app.system.service import SystemService

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/status", response_model=SystemStatus)
async def status(service: Annotated[SystemService, Depends(get_system_service)]) -> SystemStatus:
    return service.status()
