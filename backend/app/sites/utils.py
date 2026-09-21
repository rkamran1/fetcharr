"""Pure helpers: which site a URL belongs to, which cookies it keeps, and their health (§8)."""

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import urlsplit

from app.ytdlp.cookies import CookieLine

CookieStatus = Literal["none", "valid", "expiring", "expired", "flagged"]

#: The built-in sites (requirements §8); the migration seeds exactly these.
BUILTIN_SITES: dict[str, tuple[str, list[str]]] = {
    "youtube": ("YouTube", ["youtube.com", "youtu.be", "youtube-nocookie.com", "google.com"]),
    "bilibili": ("Bilibili", ["bilibili.com", "bilibili.tv", "b23.tv"]),
    "dailymotion": ("Dailymotion", ["dailymotion.com", "dai.ly"]),
}
#: A file whose earliest expiry is closer than this is "expiring".
EXPIRING_WITHIN = timedelta(days=14)
#: Tracking cookies that live minutes (YouTube's `GPS`) sit beside year-long sign-in ones;
#: counting them would call every fresh upload expired within the hour (plan-gate decision).
SHORT_LIVED = timedelta(hours=24)


def host_matches(host: str, domain: str) -> bool:
    """`m.youtube.com` matches `youtube.com`; `notyoutube.com` and `youtube.com.evil` don't."""
    host = host.lower().strip(".")
    domain = domain.lower().strip(".")
    return bool(domain) and (host == domain or host.endswith(f".{domain}"))


def match_site(url: str, sites: Iterable[tuple[str, list[str]]]) -> str | None:
    """The key of the site whose domain matches the URL's host; the longest domain wins."""
    host = urlsplit(url).hostname or ""
    best: tuple[int, str] | None = None
    for key, domains in sorted(sites):
        for domain in domains:
            if host_matches(host, domain) and (best is None or len(domain) > best[0]):
                best = (len(domain), key)
    return best[1] if best else None


def keep_for_domains(cookies: list[CookieLine], domains: list[str]) -> list[CookieLine]:
    """Only this site's cookies: a browser export usually holds every site's (§8)."""
    return [c for c in cookies if any(host_matches(c.domain, d) for d in domains)]


def summary(cookies: list[CookieLine], now: datetime) -> tuple[int, datetime | None]:
    """The count, and the earliest expiry that isn't a session or short-lived cookie.

    When nothing outlives the next 24 h, the latest expiry stands in: a file that is
    entirely expired, or about to be, must say so rather than look healthy.
    """
    timed = [
        datetime.fromtimestamp(cookie.expires, UTC).replace(tzinfo=None)
        for cookie in cookies
        if cookie.expires > 0
    ]
    lasting = [expiry for expiry in timed if expiry > now + SHORT_LIVED]
    earliest = min(lasting) if lasting else max(timed, default=None)
    return len(cookies), earliest


def cookie_status(
    has_cookies: bool, flagged: bool, earliest_expiry: datetime | None, now: datetime
) -> CookieStatus:
    if not has_cookies:
        return "none"
    if flagged:
        return "flagged"
    if earliest_expiry is None:
        return "valid"
    if earliest_expiry <= now:
        return "expired"
    if earliest_expiry - now < EXPIRING_WITHIN:
        return "expiring"
    return "valid"
