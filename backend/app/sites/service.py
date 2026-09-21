"""Sites and their encrypted cookie files: upload, status, and use by inspect and download (§8)."""

import asyncio
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, select

from app.db.base import utcnow
from app.db.session import Database
from app.inspections.models import Inspection
from app.settings.utils import decrypt, encrypt
from app.sites.exceptions import BuiltinSite, InvalidCookies, SiteExists, SiteNotFound
from app.sites.models import Site, SiteCookies
from app.sites.schemas import CookiesUploaded, SiteCreate, SiteRead
from app.sites.utils import cookie_status, keep_for_domains, match_site, summary
from app.ytdlp.cookies import CookieFileError, parse, render


@dataclass(frozen=True)
class SiteCookiesInUse:
    """The plaintext handed to yt-dlp for one run, and which site it belongs to."""

    site_key: str
    text: str


@dataclass(frozen=True)
class _Filtered:
    text: str
    count: int
    earliest_expiry: datetime | None


class SitesService:
    def __init__(self, db: Database, secret_key: bytes) -> None:
        self.db = db
        self.secret_key = secret_key

    # ------------------------------------------------------------------ the API

    async def read_all(self) -> list[SiteRead]:
        async with self.db.read_session() as session:
            sites = list(
                await session.scalars(select(Site).order_by(Site.builtin.desc(), Site.key))
            )
            cookies = {row.site_key: row for row in await session.scalars(select(SiteCookies))}
        now = utcnow()
        return [_read(site, cookies.get(site.key), now) for site in sites]

    async def create(self, body: SiteCreate) -> SiteRead:
        async with self.db.write_session() as session:
            if await session.get(Site, body.key) is not None:
                raise SiteExists(body.key)
            site = Site(
                key=body.key,
                label=body.key,
                domains=list(dict.fromkeys(body.domains)),
                builtin=False,
            )
            session.add(site)
        return _read(site, None, utcnow())

    async def delete(self, key: str) -> None:
        async with self.db.write_session() as session:
            site = await session.get(Site, key)
            if site is None:
                raise SiteNotFound(key)
            if site.builtin:
                raise BuiltinSite(key)
            await session.execute(delete(SiteCookies).where(SiteCookies.site_key == key))
            await session.delete(site)

    async def upload(self, key: str, text: str) -> CookiesUploaded:
        """Keep only this site's cookies, encrypt them and replace the stored file (§8)."""
        site = await self._site(key)
        try:
            filtered = await asyncio.to_thread(_filter, text, site.domains)
        except CookieFileError as error:
            raise InvalidCookies(error.message) from error

        if filtered.count == 0:
            async with self.db.read_session() as session:
                existing = await session.get(SiteCookies, key)
            warning = (
                f"None of these cookies belong to {', '.join(site.domains)}, so nothing was "
                "saved. Export the cookies while signed in to this site."
            )
            return CookiesUploaded(site=_read(site, existing, utcnow()), warning=warning)

        blob = await asyncio.to_thread(encrypt, filtered.text, self.secret_key)
        now = utcnow()
        async with self.db.write_session() as session:
            row = await session.get(SiteCookies, key)
            if row is None:
                row = SiteCookies(site_key=key, last_used_at=None)
                session.add(row)
            row.enc_blob = blob
            row.cookie_count = filtered.count
            row.earliest_expiry = filtered.earliest_expiry
            # A new file is a fresh start: the old one's failures say nothing about it.
            row.flagged_invalid = False
            row.uploaded_at = now
            row.updated_at = now
            # Cached inspections ran without these cookies; the next inspect must see them.
            await session.execute(delete(Inspection).where(Inspection.site_key == key))
        return CookiesUploaded(site=_read(site, row, now))

    async def delete_cookies(self, key: str) -> None:
        await self._site(key)
        async with self.db.write_session() as session:
            await session.execute(delete(SiteCookies).where(SiteCookies.site_key == key))

    # --------------------------------------------------- inspect and download

    async def site_key_for(self, url: str) -> str | None:
        async with self.db.read_session() as session:
            sites = [(site.key, site.domains) for site in await session.scalars(select(Site))]
        return match_site(url, sites)

    async def cookies_for_site(self, key: str) -> SiteCookiesInUse | None:
        async with self.db.read_session() as session:
            row = await session.get(SiteCookies, key)
            blob = row.enc_blob if row is not None else None
        if blob is None:
            return None
        text = await asyncio.to_thread(decrypt, blob, self.secret_key)
        return SiteCookiesInUse(site_key=key, text=text) if text else None

    async def used(self, key: str, refreshed: str | None = None) -> None:
        """After a successful run: note the use, and keep yt-dlp's refreshed file (§8)."""
        filtered: _Filtered | None = None
        blob: str | None = None
        if refreshed is not None:
            site = await self._site(key)
            try:
                filtered = await asyncio.to_thread(_filter, refreshed, site.domains)
            except CookieFileError:
                filtered = None
            if filtered is not None and filtered.count:
                blob = await asyncio.to_thread(encrypt, filtered.text, self.secret_key)
        now = utcnow()
        async with self.db.write_session() as session:
            row = await session.get(SiteCookies, key)
            if row is None:  # deleted while the run was going
                return
            row.last_used_at = now
            if filtered is not None and blob is not None:
                # Two runs of one site at once: the last writer wins, harmless for refreshes.
                row.enc_blob = blob
                row.cookie_count = filtered.count
                row.earliest_expiry = filtered.earliest_expiry
                row.updated_at = now

    async def flag(self, key: str) -> None:
        """An auth-type failure while these cookies were in use: possibly invalid (§8)."""
        async with self.db.write_session() as session:
            row = await session.get(SiteCookies, key)
            if row is not None:
                row.flagged_invalid = True

    async def _site(self, key: str) -> Site:
        async with self.db.read_session() as session:
            site = await session.get(Site, key)
        if site is None:
            raise SiteNotFound(key)
        return site


def _filter(text: str, domains: list[str]) -> _Filtered:
    kept = keep_for_domains(parse(text), domains)
    count, earliest = summary(kept, utcnow())
    return _Filtered(text=render(kept), count=count, earliest_expiry=earliest)


def _read(site: Site, cookies: SiteCookies | None, now: datetime) -> SiteRead:
    return SiteRead(
        key=site.key,
        label=site.label,
        domains=list(site.domains),
        builtin=site.builtin,
        status=cookie_status(
            cookies is not None,
            bool(cookies and cookies.flagged_invalid),
            cookies.earliest_expiry if cookies else None,
            now,
        ),
        cookie_count=cookies.cookie_count if cookies else None,
        earliest_expiry=cookies.earliest_expiry if cookies else None,
        last_used_at=cookies.last_used_at if cookies else None,
        uploaded_at=cookies.uploaded_at if cookies else None,
    )
