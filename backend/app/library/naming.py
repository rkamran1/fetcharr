"""Radarr/Sonarr-compatible folder and file names (requirements §7.2). Pure functions."""

import re
import unicodedata
from dataclasses import asdict, dataclass, fields
from datetime import date
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any

MAX_NAME_BYTES = 255
# Room for the extension, a sidecar's `.<lang>` and a keep-both ` (n)` (requirements §7.3).
SUFFIX_RESERVE_BYTES = 40

#: Every token a template may use (§7.2). The order matters: `season:00` before `season`.
TOKEN_NAMES = (
    "Movie Title",
    "Release Year",
    "Series Title",
    "season:00",
    "season",
    "episode:00",
    "Episode Title",
    "Air-Date",
    "Quality Full",
    "Title",
    "Id",
)
TOKENS = frozenset(TOKEN_NAMES)

_TOKEN = re.compile(r"\{(" + "|".join(re.escape(name) for name in TOKEN_NAMES) + r")\}")
_ANY_TOKEN = re.compile(r"\{[^{}]*\}")
_BLOCK = re.compile(r"\([^()]*\)|\[[^\[\]]*\]")
_ILLEGAL = re.compile(r'[\\/*?"<>|]')
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class Movie:
    title: str
    year: int | None


@dataclass(frozen=True)
class Episode:
    series_title: str
    season: int
    episode: int
    episode_title: str


@dataclass(frozen=True)
class DailyEpisode:
    series_title: str
    air_date: date
    episode_title: str
    season: int | None = None


@dataclass(frozen=True)
class Other:
    title: str
    id: str


Target = Movie | Episode | DailyEpisode | Other


@dataclass(frozen=True)
class Templates:
    movie_folder: str = "{Movie Title} ({Release Year})"
    movie_file: str = "{Movie Title} ({Release Year}) {Quality Full}"
    series_folder: str = "{Series Title}"
    season_folder: str = "Season {season}"
    specials_folder: str = "Specials"
    standard_episode: str = (
        "{Series Title} - S{season:00}E{episode:00} - {Episode Title} {Quality Full}"
    )
    daily_episode: str = "{Series Title} - {Air-Date} - {Episode Title} {Quality Full}"
    other: str = "{Title} [{Id}]"


DEFAULT_TEMPLATES = Templates()
#: The editable template names, in the order Settings shows them.
TEMPLATE_KEYS = tuple(field.name for field in fields(Templates))


class ColonMode(StrEnum):
    SMART = "smart"
    DELETE = "delete"
    DASH = "dash"
    SPACE_DASH = "space_dash"
    SPACE_DASH_SPACE = "space_dash_space"


_COLON_REPLACEMENTS = {
    ColonMode.DELETE: "",
    ColonMode.DASH: "-",
    ColonMode.SPACE_DASH: " -",
    ColonMode.SPACE_DASH_SPACE: " - ",
}


def replace_colons(text: str, colon: ColonMode = ColonMode.SMART) -> str:
    if colon is ColonMode.SMART:
        return text.replace(": ", " - ").replace(":", "-")
    return text.replace(":", _COLON_REPLACEMENTS[colon])


def sanitize(text: str, colon: ColonMode = ColonMode.SMART) -> str:
    """One path component: no separators or illegal characters, never `.` or `..`."""
    text = unicodedata.normalize("NFC", text)
    text = _ILLEGAL.sub("", replace_colons(text, colon))
    return _WHITESPACE.sub(" ", text).strip(" .")


def quality_label(width: int, height: int) -> str:
    """Arr web quality from the shorter side, so vertical video counts by its width."""
    side = min(width, height)
    if side <= 480:
        return "WEBDL-480p"
    if side <= 720:
        return "WEBDL-720p"
    if side >= 2160:
        return "WEBDL-2160p"
    # Arr has no 1440p tier.
    return "WEBDL-1080p"


def _render(template: str, values: dict[str, str]) -> str:
    def drop_empty(block: re.Match[str]) -> str:
        tokens = _TOKEN.findall(block.group())
        return "" if any(not values[token] for token in tokens) else block.group()

    text = _BLOCK.sub(drop_empty, template)
    return _WHITESPACE.sub(" ", _TOKEN.sub(lambda m: values[m.group(1)], text)).strip(" .")


def _name(template: str, values: dict[str, str], colon: ColonMode, limit: int) -> str:
    values = {token: sanitize(value, colon) for token, value in values.items()}
    name = _render(template, values)
    overflow = len(name.encode()) - limit
    # Shorten the episode title first; it is the least important part of the name.
    while overflow > 0 and values.get("Episode Title"):
        title = values["Episode Title"].encode()
        kept = title[: max(len(title) - overflow, 0)].decode(errors="ignore")
        values["Episode Title"] = sanitize(kept, colon)
        name = _render(template, values)
        overflow = len(name.encode()) - limit
    if overflow > 0:
        name = name.encode()[:limit].decode(errors="ignore").strip(" .")
    if not name:
        raise ValueError(f"template {template!r} rendered an empty name")
    return name


def _values(target: Target, quality: str) -> dict[str, str]:
    values = dict.fromkeys(
        ("Movie Title", "Release Year", "Series Title", "season", "season:00", "episode:00")
        + ("Episode Title", "Air-Date", "Title", "Id"),
        "",
    )
    values["Quality Full"] = quality
    match target:
        case Movie():
            values["Movie Title"] = target.title
            values["Release Year"] = "" if target.year is None else str(target.year)
        case Episode():
            values["Series Title"] = target.series_title
            values["season"] = str(target.season)
            values["season:00"] = f"{target.season:02d}"
            values["episode:00"] = f"{target.episode:02d}"
            values["Episode Title"] = target.episode_title
        case DailyEpisode():
            season = target.air_date.year if target.season is None else target.season
            values["Series Title"] = target.series_title
            values["season"] = str(season)
            values["season:00"] = f"{season:02d}"
            values["Air-Date"] = target.air_date.isoformat()
            values["Episode Title"] = target.episode_title
        case Other():
            values["Title"] = target.title
            values["Id"] = target.id
    return values


def build_path(
    target: Target,
    quality: str,
    ext: str,
    templates: Templates = DEFAULT_TEMPLATES,
    colon: ColonMode = ColonMode.SMART,
) -> PurePosixPath:
    """The video's path relative to COMPLETED_DIR; `ext` includes the dot (`.mkv`)."""
    values = _values(target, quality)
    file_limit = MAX_NAME_BYTES - SUFFIX_RESERVE_BYTES

    def folder(template: str) -> str:
        return _name(template, values, colon, MAX_NAME_BYTES)

    match target:
        case Movie():
            base = _name(templates.movie_file, values, colon, file_limit)
            return PurePosixPath("movies", folder(templates.movie_folder), base + ext)
        case Episode() | DailyEpisode():
            template = (
                templates.standard_episode
                if isinstance(target, Episode)
                else templates.daily_episode
            )
            base = _name(template, values, colon, file_limit)
            season = (
                templates.specials_folder if values["season"] == "0" else templates.season_folder
            )
            return PurePosixPath(
                "tv-shows", folder(templates.series_folder), folder(season), base + ext
            )
        case Other():
            base = _name(templates.other, values, colon, file_limit)
            return PurePosixPath("other", base + ext)


def snapshot(templates: Templates, colon: ColonMode) -> dict[str, Any]:
    """What a request stores, so a later Settings change cannot rename its files (§7.2)."""
    return {"templates": asdict(templates), "colon": str(colon)}


def from_snapshot(value: dict[str, Any] | None) -> tuple[Templates, ColonMode]:
    """The naming a request was created with; the defaults for rows written before M10b."""
    if not value:
        return DEFAULT_TEMPLATES, ColonMode.SMART
    stored = value.get("templates") or {}
    templates = Templates(
        **{key: stored[key] for key in TEMPLATE_KEYS if isinstance(stored.get(key), str)}
    )
    try:
        colon = ColonMode(value.get("colon"))
    except ValueError:
        colon = ColonMode.SMART
    return templates, colon


def unknown_tokens(template: str) -> list[str]:
    """The `{…}` groups a template uses that aren't in TOKENS, in the order they appear."""
    found = [match.group() for match in _ANY_TOKEN.finditer(template)]
    return list(dict.fromkeys(token for token in found if token[1:-1] not in TOKENS))


#: What Settings renders the templates against, so an edit shows its effect (§7.2, §11).
EXAMPLE_QUALITY = "WEBDL-1080p"
EXAMPLE_EXT = ".mkv"
EXAMPLE_MOVIE = Movie(title="Blade Runner: The Final Cut", year=2007)
EXAMPLE_EPISODE = Episode(
    series_title="Star Trek: Discovery", season=1, episode=5, episode_title="Choose Your Pain"
)
EXAMPLE_SPECIAL = Episode(
    series_title="Star Trek: Discovery", season=0, episode=2, episode_title="Runaway"
)
EXAMPLE_DAILY = DailyEpisode(
    series_title="The Daily Show",
    air_date=date(2026, 1, 31),
    episode_title="Tonight: The Interview",
)
EXAMPLE_OTHER = Other(title="A Talk: Part One", id="dQw4w9WgXcQ")
EXAMPLES: dict[str, Target] = {
    "movie": EXAMPLE_MOVIE,
    "episode": EXAMPLE_EPISODE,
    "specials": EXAMPLE_SPECIAL,
    "daily": EXAMPLE_DAILY,
    "other": EXAMPLE_OTHER,
}


def preview(
    templates: Templates = DEFAULT_TEMPLATES, colon: ColonMode = ColonMode.SMART
) -> dict[str, str]:
    """One example path per kind of target, so every template is visible in Settings."""
    return {
        kind: str(build_path(target, EXAMPLE_QUALITY, EXAMPLE_EXT, templates, colon))
        for kind, target in EXAMPLES.items()
    }


def sidecar_name(video_name: str, lang: str, ext: str) -> str:
    """`<video base>.<lang><ext>`, e.g. `Show - S01E01 - Pilot WEBDL-1080p.en.srt`."""
    return f"{PurePosixPath(video_name).stem}.{sanitize(lang)}{ext}"
