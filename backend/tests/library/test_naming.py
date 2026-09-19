import unicodedata
from datetime import date
from pathlib import PurePosixPath

import pytest

from app.library.naming import (
    MAX_NAME_BYTES,
    SUFFIX_RESERVE_BYTES,
    ColonMode,
    DailyEpisode,
    Episode,
    Movie,
    Other,
    build_path,
    quality_label,
    replace_colons,
    sanitize,
    sidecar_name,
)

HD = "WEBDL-1080p"


def test_movie_path() -> None:
    path = build_path(Movie("Big Buck Bunny", 2008), HD, ".mkv")

    assert path == PurePosixPath(
        "movies/Big Buck Bunny (2008)/Big Buck Bunny (2008) WEBDL-1080p.mkv"
    )


def test_standard_episode_path() -> None:
    path = build_path(Episode("Some Show", 1, 1, "Pilot"), HD, ".mkv")

    assert path == PurePosixPath(
        "tv-shows/Some Show/Season 1/Some Show - S01E01 - Pilot WEBDL-1080p.mkv"
    )


def test_season_zero_goes_to_specials() -> None:
    path = build_path(Episode("Some Show", 0, 3, "Behind the Scenes"), HD, ".mkv")

    assert path == PurePosixPath(
        "tv-shows/Some Show/Specials/Some Show - S00E03 - Behind the Scenes WEBDL-1080p.mkv"
    )


def test_daily_episode_path() -> None:
    path = build_path(DailyEpisode("Daily Show", date(2024, 3, 15), "News"), HD, ".mkv")

    assert path == PurePosixPath(
        "tv-shows/Daily Show/Season 2024/Daily Show - 2024-03-15 - News WEBDL-1080p.mkv"
    )


def test_daily_episode_explicit_season() -> None:
    path = build_path(DailyEpisode("Daily Show", date(2024, 3, 15), "News", season=7), HD, ".mkv")

    assert path.parent == PurePosixPath("tv-shows/Daily Show/Season 7")
    assert path.name == "Daily Show - 2024-03-15 - News WEBDL-1080p.mkv"


def test_other_path() -> None:
    path = build_path(Other("Some Video Title", "dQw4w9WgXcQ"), HD, ".webm")

    assert path == PurePosixPath("other/Some Video Title [dQw4w9WgXcQ].webm")


@pytest.mark.parametrize(
    ("width", "height", "label"),
    [
        (640, 480, "WEBDL-480p"),
        (854, 481, "WEBDL-720p"),
        (1280, 720, "WEBDL-720p"),
        (1920, 721, "WEBDL-1080p"),
        (1920, 1080, "WEBDL-1080p"),
        (1080, 1920, "WEBDL-1080p"),
        (1920, 1081, "WEBDL-1080p"),
        (2560, 1440, "WEBDL-1080p"),
        (4096, 2159, "WEBDL-1080p"),
        (3840, 2160, "WEBDL-2160p"),
        (7680, 4320, "WEBDL-2160p"),
    ],
)
def test_quality_label_boundaries(width: int, height: int, label: str) -> None:
    assert quality_label(width, height) == label


@pytest.mark.parametrize(
    ("mode", "title_sub", "clock"),
    [
        (ColonMode.SMART, "Title - Sub", "10-30"),
        (ColonMode.DELETE, "Title Sub", "1030"),
        (ColonMode.DASH, "Title- Sub", "10-30"),
        (ColonMode.SPACE_DASH, "Title - Sub", "10 -30"),
        (ColonMode.SPACE_DASH_SPACE, "Title - Sub", "10 - 30"),
    ],
)
def test_colon_modes(mode: ColonMode, title_sub: str, clock: str) -> None:
    assert sanitize("Title: Sub", mode) == title_sub
    assert sanitize("10:30", mode) == clock
    assert build_path(Other("Title: Sub", ""), HD, ".mkv", colon=mode).name == f"{title_sub}.mkv"


def test_smart_is_the_default() -> None:
    assert replace_colons("Title: Sub 10:30") == "Title - Sub 10-30"


def test_sanitize_removes_illegal_characters() -> None:
    assert sanitize('a\\b/c*d?e"f<g>h|i') == "abcdefghi"


def test_sanitize_collapses_whitespace_and_trims() -> None:
    assert sanitize("  ..Some \t  Show\n Title.. ") == "Some Show Title"


def test_sanitize_nfc_normalises() -> None:
    decomposed = "Café"

    result = sanitize(decomposed)

    assert result == "Café"
    assert unicodedata.is_normalized("NFC", result)


def _file_limit() -> int:
    return MAX_NAME_BYTES - SUFFIX_RESERVE_BYTES


def test_long_episode_title_truncated_first() -> None:
    path = build_path(Episode("Some Show", 1, 1, "x" * 400), HD, ".mkv")

    base = path.stem
    assert len(base.encode()) == _file_limit()
    assert base.startswith("Some Show - S01E01 - xxx")
    assert base.endswith(" WEBDL-1080p")
    assert path.parent == PurePosixPath("tv-shows/Some Show/Season 1")
    assert len(sidecar_name(path.name, "en", ".srt").encode()) <= MAX_NAME_BYTES


def test_multibyte_cap_never_splits_a_character() -> None:
    title = "日本語のタイトル" * 40

    path = build_path(Episode("番組", 1, 2, title), HD, ".mkv")

    base = path.stem
    assert len(base.encode()) <= _file_limit()
    assert len(base.encode()) > _file_limit() - 3
    kept = base.removeprefix("番組 - S01E02 - ").removesuffix(" WEBDL-1080p")
    assert kept and title.startswith(kept)
    assert "�" not in base


def test_cap_falls_back_to_whole_name() -> None:
    path = build_path(Episode("S" * 400, 1, 1, "Pilot"), HD, ".mkv")

    assert len(path.name.encode()) <= MAX_NAME_BYTES
    assert len(path.stem.encode()) <= _file_limit()
    assert len(path.parts[1].encode()) == MAX_NAME_BYTES


def test_movie_without_year_has_no_empty_parentheses() -> None:
    path = build_path(Movie("Big Buck Bunny", None), HD, ".mkv")

    assert path == PurePosixPath("movies/Big Buck Bunny/Big Buck Bunny WEBDL-1080p.mkv")


def test_other_without_id_has_no_empty_brackets() -> None:
    assert build_path(Other("Title", ""), HD, ".mkv") == PurePosixPath("other/Title.mkv")


def test_sidecar_name() -> None:
    assert (
        sidecar_name("Some Show - S01E01 - Pilot WEBDL-1080p.mkv", "en", ".srt")
        == "Some Show - S01E01 - Pilot WEBDL-1080p.en.srt"
    )


@pytest.mark.parametrize(
    "target",
    [
        Movie("../../etc", 2008),
        Movie("..", None),
        Movie("/etc/passwd", 2008),
        Episode("../..", 1, 1, "/abs/../path"),
        Episode("a/b\\c", 1, 1, ".."),
        DailyEpisode("..", date(2024, 1, 1), "../x"),
        Other("../../../../tmp/evil", "../id"),
        Other("..", ""),
    ],
)
def test_hostile_titles_stay_single_components(
    target: Movie | Episode | DailyEpisode | Other,
) -> None:
    try:
        path = build_path(target, HD, ".mkv")
    except ValueError:
        return  # nothing usable was left; the caller fails instead of writing anywhere

    assert not path.is_absolute()
    for part in path.parts:
        assert part not in ("", ".", "..")
        assert "/" not in part and "\\" not in part
    assert len(path.parts) == {"movies": 3, "tv-shows": 4, "other": 2}[path.parts[0]]
