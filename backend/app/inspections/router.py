"""Inspect endpoint (requirements §5 step 1, §11)."""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.inspections.dependencies import get_inspection_service
from app.inspections.exceptions import InspectError
from app.inspections.schemas import InspectRequest, InspectResult
from app.inspections.service import InspectionService

router = APIRouter(prefix="/api")


@router.post("/inspect", response_model=InspectResult)
async def inspect(
    body: InspectRequest,
    service: Annotated[InspectionService, Depends(get_inspection_service)],
) -> InspectResult | JSONResponse:
    try:
        return await service.inspect(body.url)
    except InspectError as error:
        return JSONResponse(
            status_code=error.status,
            content={
                "detail": error.detail,
                "needs_cookies": error.needs_cookies,
                "site_key": error.site_key,
            },
        )
