"""Authentication dependencies for the ``/api`` routes (requirements §9).

``require_auth`` accepts a valid ``X-Api-Key`` header or a valid session cookie. Requests
authenticated by cookie that change state must come from the same origin (CSRF check);
API-key requests are exempt.
"""

from dataclasses import dataclass
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request, Response

from app.auth.service import AuthService
from app.auth.utils import COOKIE_NAME, needs_slide, set_session_cookie

STATE_CHANGING = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@dataclass(frozen=True)
class Auth:
    session_id: str | None  # None when authenticated with the API key


def get_auth_service(request: Request) -> AuthService:
    return AuthService(request.app.state.db, request.app.state.login_limiter)


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=401, detail="Not authenticated")


def _verify_origin(request: Request) -> None:
    if request.method not in STATE_CHANGING:
        return
    source = request.headers.get("origin") or request.headers.get("referer")
    host = request.headers.get("host")
    if not source or not host or urlsplit(source).netloc != host:
        raise HTTPException(status_code=403, detail="Origin not allowed")


async def check_origin(request: Request) -> None:
    """For the public routes: apply the Origin check whenever a session cookie is sent."""
    if COOKIE_NAME in request.cookies:
        _verify_origin(request)


async def require_auth(
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> Auth:
    api_key = request.headers.get("x-api-key")
    if api_key is not None:
        if not await service.api_key_valid(api_key):
            raise _unauthorized()
        return Auth(session_id=None)

    session_id = request.cookies.get(COOKIE_NAME)
    if not session_id:
        raise _unauthorized()
    auth_session = await service.valid_session(session_id)
    if auth_session is None:
        raise _unauthorized()
    _verify_origin(request)
    if needs_slide(auth_session.expires_at):
        await service.slide_session(session_id)
        set_session_cookie(response, session_id, secure=request.app.state.settings.cookie_secure)
    return Auth(session_id=session_id)
