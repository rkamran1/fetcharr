"""The Netscape cookie file yt-dlp reads with `--cookies` and rewrites on exit (§8).

Parsing and rendering are pure; ``write_private`` touches the disk, so callers run it
through ``asyncio.to_thread`` (§3.2).
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path

HEADER = "# Netscape HTTP Cookie File"
#: curl and yt-dlp mark HttpOnly cookies with this prefix; the line is a cookie, not a comment.
HTTPONLY_PREFIX = "#HttpOnly_"
#: The plaintext is readable by its owner only, from the moment it exists (§8).
PRIVATE_MODE = 0o600
_FIELDS = 7
_COOKIE_HEADER = re.compile(r"((?:Set-)?Cookie:\s*).*", re.IGNORECASE)


class CookieFileError(Exception):
    """The text isn't a Netscape cookie file; `line` is 1-based, or 0 for the whole file."""

    def __init__(self, line: int, reason: str) -> None:
        message = f"line {line}: {reason}" if line else reason
        super().__init__(message)
        self.line = line
        self.message = message


@dataclass(frozen=True)
class CookieLine:
    """One cookie, kept verbatim so a round trip changes nothing."""

    raw: str
    domain: str
    expires: int


def parse(text: str) -> list[CookieLine]:
    """The cookies in a Netscape file; raises CookieFileError on a wrong header or line."""
    lines = text.splitlines()
    first = next((line.strip() for line in lines if line.strip()), "")
    if first != HEADER:
        raise CookieFileError(0, f"not a Netscape cookie file (the first line must be {HEADER!r})")

    cookies = []
    for number, raw in enumerate(lines, start=1):
        line = raw.rstrip("\r\n")
        if not line.strip():
            continue
        if line.startswith("#") and not line.startswith(HTTPONLY_PREFIX):
            continue
        fields = line.split("\t")
        if len(fields) != _FIELDS:
            raise CookieFileError(number, f"expected {_FIELDS} tab-separated fields")
        expires = fields[4].strip()
        if not expires.lstrip("-").isdigit():
            raise CookieFileError(number, "the expiry must be a number")
        domain = fields[0].removeprefix(HTTPONLY_PREFIX)
        cookies.append(CookieLine(raw=line, domain=domain, expires=int(expires)))
    return cookies


def render(cookies: list[CookieLine]) -> str:
    """A Netscape file holding exactly these cookies."""
    return "".join(f"{line}\n" for line in [HEADER, "", *(c.raw for c in cookies)])


def write_private(path: Path, text: str) -> None:
    """Write `text` to `path` with mode 0600, never readable by anyone else in between."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, PRIVATE_MODE)
    with os.fdopen(descriptor, "w") as handle:
        # O_CREAT's mode doesn't apply to a file that already existed.
        os.fchmod(handle.fileno(), PRIVATE_MODE)
        handle.write(text)


def scrub(line: str) -> str:
    """The line with any `Cookie:` / `Set-Cookie:` header value redacted (§8 logging)."""
    return _COOKIE_HEADER.sub(r"\1[redacted]", line)
