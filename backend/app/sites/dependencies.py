from fastapi import Request

from app.sites.service import SitesService


def get_sites_service(request: Request) -> SitesService:
    state = request.app.state
    return SitesService(state.db, state.secret_key)
