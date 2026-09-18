"""Auth endpoints (requirements §11). ``public`` needs no session; ``protected`` does."""

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import delete, update

from app.auth.deps import Auth, require_auth
from app.auth.passwords import hash_password, hash_token, verify_password
from app.auth.sessions import clear_session_cookie, new_session, set_session_cookie
from app.db.models import Account, AuthSession

public = APIRouter(prefix="/api/auth")
protected = APIRouter(prefix="/api/auth")

Username = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
NewPassword = Annotated[str, Field(min_length=8)]


class AuthState(BaseModel):
    setup_required: bool


class NewAccount(BaseModel):
    username: Username
    password: NewPassword


class Credentials(BaseModel):
    username: str
    password: str


class PasswordChange(BaseModel):
    current_password: str
    new_password: NewPassword


class Me(BaseModel):
    username: str


class ApiKey(BaseModel):
    api_key: str


def _cookie_secure(request: Request) -> bool:
    return request.app.state.settings.cookie_secure


async def _account(request: Request) -> Account | None:
    async with request.app.state.db.read_session() as session:
        return await session.get(Account, 1)


@public.get("/state")
async def state(request: Request) -> AuthState:
    return AuthState(setup_required=await _account(request) is None)


@public.post("/setup", status_code=201)
async def setup(body: NewAccount, request: Request, response: Response) -> Me:
    password_hash = await hash_password(body.password)
    auth_session = new_session(request)
    async with request.app.state.db.write_session() as session:
        if await session.get(Account, 1) is not None:
            raise HTTPException(status_code=409, detail="Setup is already complete")
        session.add(
            Account(
                id=1,
                username=body.username,
                password_hash=password_hash,
                last_login_at=auth_session.created_at,
            )
        )
        session.add(auth_session)
    set_session_cookie(response, auth_session.id, secure=_cookie_secure(request))
    return Me(username=body.username)


@public.post("/login")
async def login(body: Credentials, request: Request, response: Response) -> Me:
    client_ip = request.client.host if request.client else "unknown"
    retry_after = request.app.state.login_limiter.hit(client_ip)
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts, try again later",
            headers={"Retry-After": str(retry_after)},
        )
    account = await _account(request)
    if (
        account is None
        or body.username.strip() != account.username
        or not await verify_password(account.password_hash, body.password)
    ):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    auth_session = new_session(request)
    async with request.app.state.db.write_session() as session:
        await session.execute(update(Account).values(last_login_at=auth_session.created_at))
        session.add(auth_session)
    set_session_cookie(response, auth_session.id, secure=_cookie_secure(request))
    return Me(username=account.username)


@protected.post("/logout", status_code=204)
async def logout(
    request: Request, response: Response, auth: Annotated[Auth, Depends(require_auth)]
) -> None:
    if auth.session_id is not None:
        async with request.app.state.db.write_session() as session:
            await session.execute(delete(AuthSession).where(AuthSession.id == auth.session_id))
    clear_session_cookie(response, secure=_cookie_secure(request))


@protected.get("/me")
async def me(request: Request) -> Me:
    account = await _account(request)
    if account is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return Me(username=account.username)


@protected.post("/password", status_code=204)
async def change_password(
    body: PasswordChange, request: Request, auth: Annotated[Auth, Depends(require_auth)]
) -> None:
    account = await _account(request)
    if account is None or not await verify_password(account.password_hash, body.current_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    password_hash = await hash_password(body.new_password)
    others = delete(AuthSession)
    if auth.session_id is not None:
        others = others.where(AuthSession.id != auth.session_id)
    async with request.app.state.db.write_session() as session:
        await session.execute(update(Account).values(password_hash=password_hash))
        await session.execute(others)


@protected.post("/api-key")
async def regenerate_api_key(request: Request) -> ApiKey:
    api_key = secrets.token_urlsafe(32)
    async with request.app.state.db.write_session() as session:
        await session.execute(update(Account).values(api_key_hash=hash_token(api_key)))
    return ApiKey(api_key=api_key)
