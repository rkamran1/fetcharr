"""Settings endpoints (requirements §11). Secrets go in, never out."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.settings.dependencies import get_settings_service
from app.settings.exceptions import SettingsError
from app.settings.schemas import (
    NamingPreview,
    NamingPreviewRead,
    SettingsRead,
    SettingsUpdate,
    YtdlpUpdateRead,
)
from app.settings.service import SettingsService

router = APIRouter(prefix="/api/settings", tags=["settings"])

Service = Annotated[SettingsService, Depends(get_settings_service)]


@router.get("", response_model=SettingsRead)
async def read_settings(service: Service) -> SettingsRead:
    return await service.read()


@router.patch("", response_model=SettingsRead)
async def update_settings(body: SettingsUpdate, service: Service) -> SettingsRead:
    try:
        return await service.update(body)
    except SettingsError as error:
        raise HTTPException(status_code=error.status, detail=error.detail) from error


@router.post("/naming/preview", response_model=NamingPreviewRead)
async def preview_naming(body: NamingPreview, service: Service) -> NamingPreviewRead:
    """The live example under the template fields; invalid templates come back as errors."""
    try:
        return await service.preview_naming(body)
    except SettingsError as error:
        raise HTTPException(status_code=error.status, detail=error.detail) from error


@router.post("/yt-dlp/update", response_model=YtdlpUpdateRead)
async def update_ytdlp(service: Service) -> YtdlpUpdateRead:
    try:
        return await service.update_ytdlp()
    except SettingsError as error:
        raise HTTPException(status_code=error.status, detail=error.detail) from error
