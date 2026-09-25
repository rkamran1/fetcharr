"""Presets endpoints (requirements §11)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response

from app.presets.dependencies import get_presets_service
from app.presets.exceptions import PresetError
from app.presets.schemas import PresetCreate, PresetRead, PresetUpdate
from app.presets.service import PresetsService

router = APIRouter(prefix="/api/presets", tags=["presets"])

Service = Annotated[PresetsService, Depends(get_presets_service)]


def _http(error: PresetError) -> HTTPException:
    return HTTPException(status_code=error.status, detail=error.detail)


@router.get("", response_model=list[PresetRead])
async def list_presets(service: Service) -> list[PresetRead]:
    return await service.read_all()


@router.post("", response_model=PresetRead, status_code=201)
async def create_preset(body: PresetCreate, service: Service) -> PresetRead:
    return await service.create(body)


@router.patch("/{preset_id}", response_model=PresetRead)
async def update_preset(preset_id: int, body: PresetUpdate, service: Service) -> PresetRead:
    try:
        return await service.update(preset_id, body)
    except PresetError as error:
        raise _http(error) from error


@router.delete("/{preset_id}", status_code=204)
async def delete_preset(preset_id: int, service: Service) -> Response:
    try:
        await service.delete(preset_id)
    except PresetError as error:
        raise _http(error) from error
    return Response(status_code=204)
