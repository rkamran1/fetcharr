from fastapi import Request

from app.inspections.service import InspectionService
from app.sites.service import SitesService


def get_inspection_service(request: Request) -> InspectionService:
    state = request.app.state
    return InspectionService(state.db, SitesService(state.db, state.secret_key))
