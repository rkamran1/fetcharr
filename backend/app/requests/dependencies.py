from fastapi import Request as HttpRequest

from app.jobs.dependencies import get_job_service
from app.requests.service import RequestService
from app.settings.dependencies import get_settings_service


def get_request_service(request: HttpRequest) -> RequestService:
    state = request.app.state
    return RequestService(
        state.db,
        state.settings,
        state.hub,
        state.manager,
        get_job_service(request),
        get_settings_service(request),
    )
