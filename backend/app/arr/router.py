"""Radarr endpoints for the Settings test and the movie picker (requirements §11)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.arr.dependencies import get_arr_service
from app.arr.exceptions import ArrDomainError
from app.arr.schemas import ArrTestResult, RadarrMovieList
from app.arr.service import ArrService

router = APIRouter(prefix="/api/arr/radarr", tags=["arr"])

Service = Annotated[ArrService, Depends(get_arr_service)]


@router.post("/test", response_model=ArrTestResult)
async def test_radarr(service: Service) -> ArrTestResult:
    return await service.test()


@router.get("/movies", response_model=RadarrMovieList)
async def list_movies(service: Service, q: Annotated[str, Query()] = "") -> RadarrMovieList:
    try:
        return await service.movies(q)
    except ArrDomainError as error:
        raise HTTPException(status_code=error.status, detail=error.detail) from error
