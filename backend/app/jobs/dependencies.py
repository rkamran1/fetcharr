from fastapi import Request

from app.jobs.service import JobService


def get_job_service(request: Request) -> JobService:
    state = request.app.state
    return JobService(state.db, state.settings, state.hub, state.manager)
