from fastapi import Request as HttpRequest

from app.jobs.dependencies import get_job_service
from app.requests.service import RequestService


def get_request_service(request: HttpRequest) -> RequestService:
    state = request.app.state
    return RequestService(
        state.db, state.settings, state.hub, state.manager, get_job_service(request)
    )
