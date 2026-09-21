from fastapi import Request

from app.system.service import SystemService


def get_system_service(request: Request) -> SystemService:
    state = request.app.state
    return SystemService(state.settings.app_version, state.path_report, state.hardware)
