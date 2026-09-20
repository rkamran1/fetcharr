from fastapi import Request

from app.arr.service import ArrService
from app.settings.dependencies import get_settings_service


def get_arr_service(request: Request) -> ArrService:
    state = request.app.state
    return ArrService(get_settings_service(request), state.radarr, state.sonarr)
