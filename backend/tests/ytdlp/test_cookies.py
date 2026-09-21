import stat
from pathlib import Path

import pytest

from app.ytdlp.cookies import CookieFileError, parse, render, scrub, write_private
from tests.conftest import CANARY, YEAR_FROM_NOW, cookie_file, cookie_line


def test_parse_reads_cookies_and_httponly_lines() -> None:
    text = cookie_file(
        "# a comment",
        cookie_line(".youtube.com", expires=0),
        f"#HttpOnly_{cookie_line('.youtube.com', 'HSID')}",
    )

    cookies = parse(text)

    assert [(c.domain, c.expires) for c in cookies] == [
        (".youtube.com", 0),
        (".youtube.com", YEAR_FROM_NOW),
    ]
    assert parse(render(cookies)) == cookies


def test_parse_rejects_a_file_without_the_header() -> None:
    with pytest.raises(CookieFileError, match="not a Netscape cookie file"):
        parse(cookie_line(".youtube.com"))


def test_parse_names_the_malformed_line() -> None:
    with pytest.raises(CookieFileError, match="line 4: expected 7 tab-separated fields"):
        parse(cookie_file(cookie_line(".youtube.com"), ".youtube.com TRUE / TRUE 0 SID x"))


def test_parse_rejects_a_non_numeric_expiry() -> None:
    with pytest.raises(CookieFileError, match="line 3: the expiry must be a number"):
        parse(cookie_file(cookie_line(".youtube.com").replace("4102444800", "soon")))


def test_write_private_file_is_0600(tmp_path: Path) -> None:
    fresh = tmp_path / "fresh.txt"
    existing = tmp_path / "existing.txt"
    existing.write_text("old")
    existing.chmod(0o644)

    write_private(fresh, "one")
    write_private(existing, "two")

    assert stat.S_IMODE(fresh.stat().st_mode) == 0o600
    assert stat.S_IMODE(existing.stat().st_mode) == 0o600
    assert existing.read_text() == "two"


@pytest.mark.parametrize(
    "line",
    [
        f"[debug] Cookie: SID={CANARY}; HSID=x",
        f"Set-Cookie: SID={CANARY}; Path=/",
        f"  cookie: {CANARY}",
    ],
)
def test_scrub_redacts_cookie_headers(line: str) -> None:
    scrubbed = scrub(line)

    assert CANARY not in scrubbed
    assert "[redacted]" in scrubbed


def test_scrub_leaves_other_lines_alone() -> None:
    line = "[download]  42.0% of 10.00MiB"

    assert scrub(line) == line
