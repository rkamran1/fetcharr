from fastapi import Request

from app.arr.dependencies import get_arr_service
from app.settings.dependencies import get_settings_service
from app.system.service import SystemService


def get_system_service(request: Request) -> SystemService:
    state = request.app.state
    return SystemService(
        state.settings,
        state.hardware,
        state.manager,
        get_arr_service(request),
        get_settings_service(request),
    )
