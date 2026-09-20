from fastapi import Request

from app.inspections.service import InspectionService


def get_inspection_service(request: Request) -> InspectionService:
    return InspectionService(request.app.state.db)
