"""Radarr and Sonarr endpoints for the Settings tests and the pickers (requirements §11)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.arr.dependencies import get_arr_service
from app.arr.exceptions import ArrDomainError
from app.arr.schemas import ArrTestResult, RadarrMovieList, SonarrEpisodeList, SonarrSeriesList
from app.arr.service import ArrService

router = APIRouter(prefix="/api/arr", tags=["arr"])

Service = Annotated[ArrService, Depends(get_arr_service)]


def _http(error: ArrDomainError) -> HTTPException:
    return HTTPException(status_code=error.status, detail=error.detail)


@router.post("/radarr/test", response_model=ArrTestResult)
async def test_radarr(service: Service) -> ArrTestResult:
    return await service.test()


@router.get("/radarr/movies", response_model=RadarrMovieList)
async def list_movies(
    service: Service,
    q: Annotated[str, Query()] = "",
    missing: Annotated[bool, Query()] = False,
    refresh: Annotated[bool, Query()] = False,
) -> RadarrMovieList:
    try:
        return await service.movies(q, missing, refresh)
    except ArrDomainError as error:
        raise _http(error) from error


@router.post("/sonarr/test", response_model=ArrTestResult)
async def test_sonarr(service: Service) -> ArrTestResult:
    return await service.test_sonarr()


@router.get("/sonarr/series", response_model=SonarrSeriesList)
async def list_series(
    service: Service,
    q: Annotated[str, Query()] = "",
    missing: Annotated[bool, Query()] = False,
    refresh: Annotated[bool, Query()] = False,
) -> SonarrSeriesList:
    try:
        return await service.series(q, missing, refresh)
    except ArrDomainError as error:
        raise _http(error) from error


@router.get("/sonarr/series/{series_id}/episodes", response_model=SonarrEpisodeList)
async def list_episodes(
    series_id: int,
    service: Service,
    season: Annotated[int | None, Query()] = None,
) -> SonarrEpisodeList:
    try:
        return await service.episodes(series_id, season)
    except ArrDomainError as error:
        raise _http(error) from error
