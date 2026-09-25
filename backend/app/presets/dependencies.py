from fastapi import Request

from app.presets.service import PresetsService


def get_presets_service(request: Request) -> PresetsService:
    return PresetsService(request.app.state.db)
