"""Sites and cookies endpoints (requirements §8, §11). Cookie contents go in, never out."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response

from app.sites.dependencies import get_sites_service
from app.sites.exceptions import SiteError
from app.sites.schemas import CookiesUpload, CookiesUploaded, SiteCreate, SiteRead
from app.sites.service import SitesService

router = APIRouter(prefix="/api/sites", tags=["sites"])

Service = Annotated[SitesService, Depends(get_sites_service)]


def _http(error: SiteError) -> HTTPException:
    return HTTPException(status_code=error.status, detail=error.detail)


@router.get("", response_model=list[SiteRead])
async def list_sites(service: Service) -> list[SiteRead]:
    return await service.read_all()


@router.post("", response_model=SiteRead, status_code=201)
async def create_site(body: SiteCreate, service: Service) -> SiteRead:
    try:
        return await service.create(body)
    except SiteError as error:
        raise _http(error) from error


@router.delete("/{key}", status_code=204)
async def delete_site(key: str, service: Service) -> Response:
    try:
        await service.delete(key)
    except SiteError as error:
        raise _http(error) from error
    return Response(status_code=204)


@router.put("/{key}/cookies", response_model=CookiesUploaded)
async def upload_cookies(key: str, body: CookiesUpload, service: Service) -> CookiesUploaded:
    try:
        return await service.upload(key, body.text)
    except SiteError as error:
        raise _http(error) from error


@router.delete("/{key}/cookies", status_code=204)
async def delete_cookies(key: str, service: Service) -> Response:
    try:
        await service.delete_cookies(key)
    except SiteError as error:
        raise _http(error) from error
    return Response(status_code=204)
