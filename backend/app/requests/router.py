"""Request endpoints (requirements §11): create a download, read it back, preview its path."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.requests.dependencies import get_request_service
from app.requests.exceptions import RequestError
from app.requests.schemas import (
    CreatedRequest,
    CreateRequest,
    PathPreview,
    PreviewRequest,
    RequestFilters,
    RequestPage,
    RequestRead,
)
from app.requests.service import RequestService

router = APIRouter(prefix="/api", tags=["requests"])

Service = Annotated[RequestService, Depends(get_request_service)]


def _http(error: RequestError) -> HTTPException:
    return HTTPException(status_code=error.status, detail=error.detail)


@router.post("/requests", response_model=CreatedRequest, status_code=201)
async def create_request(body: CreateRequest, service: Service) -> CreatedRequest:
    try:
        return await service.create(body)
    except RequestError as error:
        raise _http(error) from error


@router.get("/requests", response_model=RequestPage)
async def list_requests(
    filters: Annotated[RequestFilters, Query()], service: Service
) -> RequestPage:
    return await service.history(filters)


@router.get("/requests/{request_id}", response_model=RequestRead)
async def get_request(request_id: str, service: Service) -> RequestRead:
    try:
        return await service.get(request_id)
    except RequestError as error:
        raise _http(error) from error


@router.post("/preview", response_model=PathPreview)
async def preview(body: PreviewRequest, service: Service) -> PathPreview:
    try:
        return await service.preview(body)
    except RequestError as error:
        raise _http(error) from error
