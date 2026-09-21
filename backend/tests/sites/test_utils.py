from datetime import UTC, datetime, timedelta

import pytest

from app.sites.utils import BUILTIN_SITES, cookie_status, keep_for_domains, match_site, summary
from app.ytdlp.cookies import parse
from tests.conftest import cookie_file, cookie_line

SITES = [(key, domains) for key, (_label, domains) in BUILTIN_SITES.items()]
NOW = datetime(2026, 9, 21, 12, 0)


@pytest.mark.parametrize(
    ("host", "site"),
    [
        ("youtube.com", "youtube"),
        ("www.youtube.com", "youtube"),
        ("m.youtube.com", "youtube"),
        ("youtu.be", "youtube"),
        ("music.youtube.com", "youtube"),
        ("b23.tv", "bilibili"),
        ("dai.ly", "dailymotion"),
        ("WWW.YouTube.COM", "youtube"),
        ("notyoutube.com", None),
        ("youtube.com.evil.test", None),
        ("evilyoutube.com", None),
    ],
)
def test_match_site(host: str, site: str | None) -> None:
    assert match_site(f"https://{host}/watch?v=x", SITES) == site


def test_match_site_prefers_the_longest_domain() -> None:
    sites = [*SITES, ("ytmusic", ["music.youtube.com"])]

    assert match_site("https://music.youtube.com/watch?v=x", sites) == "ytmusic"
    assert match_site("https://www.youtube.com/watch?v=x", sites) == "youtube"


def test_filter_keeps_only_site_domains() -> None:
    cookies = parse(
        cookie_file(
            cookie_line(".youtube.com"),
            f"#HttpOnly_{cookie_line('www.youtube.com', 'HSID')}",
            cookie_line(".google.com", "NID"),
            cookie_line(".github.com", "user_session"),
            cookie_line(".notyoutube.com", "x"),
        )
    )

    kept = keep_for_domains(cookies, BUILTIN_SITES["youtube"][1])

    assert [c.domain for c in kept] == [".youtube.com", "www.youtube.com", ".google.com"]


def _at(moment: datetime) -> int:
    return int(moment.replace(tzinfo=UTC).timestamp())


def test_summary_ignores_session_cookies() -> None:
    cookies = parse(cookie_file(cookie_line(".youtube.com", expires=0)))

    assert summary(cookies, NOW) == (1, None)


def test_summary_ignores_short_lived_cookies() -> None:
    in_30_minutes = NOW + timedelta(minutes=30)
    in_a_year = NOW + timedelta(days=365)
    cookies = parse(
        cookie_file(
            cookie_line(".youtube.com", "GPS", expires=_at(in_30_minutes)),
            cookie_line(".youtube.com", "SID", expires=_at(in_a_year)),
        )
    )

    assert summary(cookies, NOW) == (2, in_a_year)


def test_summary_without_lasting_cookies_reports_the_latest_expiry() -> None:
    expired = NOW - timedelta(days=2)
    soon = NOW + timedelta(hours=2)
    cookies = parse(
        cookie_file(
            cookie_line(".youtube.com", "OLD", expires=_at(NOW - timedelta(days=9))),
            cookie_line(".youtube.com", "SID", expires=_at(expired)),
        )
    )
    short = parse(cookie_file(cookie_line(".youtube.com", "GPS", expires=_at(soon))))

    assert summary(cookies, NOW) == (2, expired)
    assert summary(short, NOW) == (1, soon)


@pytest.mark.parametrize(
    ("has_cookies", "flagged", "expiry", "status"),
    [
        (False, False, None, "none"),
        (True, False, None, "valid"),
        (True, False, NOW + timedelta(days=30), "valid"),
        (True, False, NOW + timedelta(days=13), "expiring"),
        (True, False, NOW - timedelta(minutes=1), "expired"),
        (True, True, NOW + timedelta(days=30), "flagged"),
        (True, True, NOW - timedelta(days=1), "flagged"),
    ],
)
def test_cookie_status(
    has_cookies: bool, flagged: bool, expiry: datetime | None, status: str
) -> None:
    assert cookie_status(has_cookies, flagged, expiry, NOW) == status
