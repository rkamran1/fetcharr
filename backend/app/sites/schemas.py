"""Sites and their cookie status (requirements §8, §11). Cookie contents only ever go in."""

import re
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field

from app.sites.utils import CookieStatus

_KEY = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
_HOSTNAME = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9-]{2,63}$")


def _domain(value: str) -> str:
    domain = value.strip().lower().lstrip(".")
    if not _HOSTNAME.match(domain):
        raise ValueError(f"{value!r} is not a domain like example.com")
    return domain


Domain = Annotated[str, AfterValidator(_domain)]


def _key(value: str) -> str:
    key = value.strip().lower()
    if not _KEY.match(key):
        raise ValueError("a site key is 1-32 lowercase letters, digits or dashes")
    return key


class SiteRead(BaseModel):
    key: str
    label: str
    domains: list[str]
    builtin: bool
    status: CookieStatus
    cookie_count: int | None
    earliest_expiry: datetime | None
    last_used_at: datetime | None
    uploaded_at: datetime | None


class SiteCreate(BaseModel):
    key: Annotated[str, AfterValidator(_key)]
    domains: Annotated[list[Domain], Field(min_length=1)]


class CookiesUpload(BaseModel):
    """The file's text: the browser reads a chosen file itself, so upload and paste match."""

    text: Annotated[str, Field(min_length=1)]


class CookiesUploaded(BaseModel):
    site: SiteRead
    #: Set when the file held none of the site's cookies; nothing was stored then.
    warning: str | None = None
