"""Job endpoints (requirements §11)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.jobs.dependencies import get_job_service
from app.jobs.exceptions import JobError
from app.jobs.schemas import JobList, JobLogRead, JobRead
from app.jobs.service import JobService

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

Service = Annotated[JobService, Depends(get_job_service)]


def _http(error: JobError) -> HTTPException:
    return HTTPException(status_code=error.status, detail=error.detail)


@router.get("", response_model=JobList)
async def list_jobs(service: Service) -> JobList:
    return await service.list()


@router.get("/{job_id}", response_model=JobRead)
async def get_job(job_id: str, service: Service) -> JobRead:
    try:
        return await service.get(job_id)
    except JobError as error:
        raise _http(error) from error


@router.get("/{job_id}/log", response_model=JobLogRead)
async def get_job_log(job_id: str, service: Service) -> JobLogRead:
    try:
        return await service.log(job_id)
    except JobError as error:
        raise _http(error) from error


@router.post("/{job_id}/cancel", response_model=JobRead)
async def cancel_job(job_id: str, service: Service) -> JobRead:
    try:
        return await service.cancel(job_id)
    except JobError as error:
        raise _http(error) from error


@router.post("/{job_id}/retry", response_model=JobRead)
async def retry_job(job_id: str, service: Service) -> JobRead:
    try:
        return await service.retry(job_id)
    except JobError as error:
        raise _http(error) from error


@router.delete("/{job_id}", status_code=204)
async def delete_job(
    job_id: str,
    service: Service,
    delete_file: Annotated[bool, Query()] = False,
) -> Response:
    try:
        await service.delete(job_id, delete_file)
    except JobError as error:
        raise _http(error) from error
    return Response(status_code=204)
