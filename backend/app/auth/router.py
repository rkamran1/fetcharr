"""Auth endpoints (requirements §11). ``public`` needs no session; ``protected`` does."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.auth.dependencies import Auth, get_auth_service, require_auth
from app.auth.exceptions import InvalidCredentials, RateLimited, SetupAlreadyComplete, WrongPassword
from app.auth.schemas import ApiKey, AuthState, Credentials, Me, NewAccount, PasswordChange
from app.auth.service import AuthService
from app.auth.utils import clear_session_cookie, set_session_cookie

public = APIRouter(prefix="/api/auth")
protected = APIRouter(prefix="/api/auth")

Service = Annotated[AuthService, Depends(get_auth_service)]


def _cookie_secure(request: Request) -> bool:
    return request.app.state.settings.cookie_secure


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@public.get("/state")
async def state(service: Service) -> AuthState:
    return AuthState(setup_required=await service.username() is None)


@public.post("/setup", status_code=201)
async def setup(body: NewAccount, request: Request, response: Response, service: Service) -> Me:
    try:
        session_id = await service.setup(
            body.username, body.password, _client_ip(request), request.headers.get("user-agent")
        )
    except SetupAlreadyComplete:
        raise HTTPException(status_code=409, detail="Setup is already complete") from None
    set_session_cookie(response, session_id, secure=_cookie_secure(request))
    return Me(username=body.username)


@public.post("/login")
async def login(body: Credentials, request: Request, response: Response, service: Service) -> Me:
    try:
        username, session_id = await service.login(
            body.username,
            body.password,
            _client_ip(request),
            request.headers.get("user-agent"),
        )
    except RateLimited as error:
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts, try again later",
            headers={"Retry-After": str(error.retry_after)},
        ) from None
    except InvalidCredentials:
        raise HTTPException(status_code=401, detail="Invalid username or password") from None
    set_session_cookie(response, session_id, secure=_cookie_secure(request))
    return Me(username=username)


@protected.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    auth: Annotated[Auth, Depends(require_auth)],
    service: Service,
) -> None:
    await service.logout(auth.session_id)
    clear_session_cookie(response, secure=_cookie_secure(request))


@protected.get("/me")
async def me(service: Service) -> Me:
    username = await service.username()
    if username is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return Me(username=username)


@protected.post("/password", status_code=204)
async def change_password(
    body: PasswordChange, auth: Annotated[Auth, Depends(require_auth)], service: Service
) -> None:
    try:
        await service.change_password(body.current_password, body.new_password, auth.session_id)
    except WrongPassword:
        raise HTTPException(status_code=400, detail="Current password is incorrect") from None


@protected.post("/api-key")
async def regenerate_api_key(service: Service) -> ApiKey:
    return ApiKey(api_key=await service.regenerate_api_key())
