"""The allow-listed yt-dlp download options (requirements §4)."""

import re
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.transcode.profiles import QUALITY_MAX, QUALITY_MIN, TranscodeProfile

Quality = Literal["144p", "240p", "360p", "480p", "720p", "1080p", "1440p", "2160p", "4k", "best"]
Container = Literal["mkv", "mp4"]
SubtitleMode = Literal["off", "embed", "sidecar"]
SponsorBlockMode = Literal["off", "mark", "remove"]
VideoCodec = Literal["any", "h264", "vp9", "av1"]

#: A language tag as yt-dlp prints it: `en`, `pt-BR`, `zh-Hans`. Shape only; the UI offers
#: the languages the inspection actually found (§5 step 1).
_LANGUAGE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
#: yt-dlp's `--limit-rate`: bytes per second, optionally in K or M (e.g. `500K`, `1.5M`).
_RATE = re.compile(r"^[1-9]\d*(\.\d+)?[KM]?$")

#: The SponsorBlock categories yt-dlp documents for `--sponsorblock-mark`.
MARK_CATEGORIES = frozenset(
    {
        "sponsor",
        "intro",
        "outro",
        "selfpromo",
        "preview",
        "filler",
        "interaction",
        "music_offtopic",
        "poi_highlight",
        "all",
    }
)
#: `--sponsorblock-remove` cuts the file, so the two chapter-only categories are not offered.
REMOVE_CATEGORIES = MARK_CATEGORIES - {"poi_highlight"}
#: What `mark` and `remove` mean when no explicit category list was picked (§5 step 2d).
DEFAULT_MARK = ("all",)
DEFAULT_REMOVE = ("sponsor", "selfpromo", "interaction")


def _unique(values: list[str]) -> list[str]:
    """De-duplicate, keeping the order the user picked."""
    return list(dict.fromkeys(values))


class SubtitleOptions(BaseModel):
    """Which subtitles to fetch and whether they end up embedded or beside the file (§5)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: SubtitleMode = "off"
    languages: tuple[str, ...] = ()
    include_auto_captions: bool = False

    @field_validator("languages", mode="after")
    @classmethod
    def _languages_are_language_tags(cls, languages: tuple[str, ...]) -> tuple[str, ...]:
        for language in languages:
            if not _LANGUAGE.match(language):
                raise ValueError(f"{language!r} is not a language code")
        return tuple(_unique(list(languages)))

    @model_validator(mode="after")
    def _a_mode_needs_a_language(self) -> Self:
        if self.mode != "off" and not self.languages:
            raise ValueError("pick at least one subtitle language")
        return self


class SponsorBlockOptions(BaseModel):
    """Mark the sponsor segments as chapters, or cut them out (§5 step 2d)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: SponsorBlockMode = "off"
    #: Empty means the mode's own default: `all` for mark, the three ad categories for remove.
    categories: tuple[str, ...] = ()

    @field_validator("categories", mode="after")
    @classmethod
    def _categories_are_unique(cls, categories: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_unique(list(categories)))

    @model_validator(mode="after")
    def _categories_are_allow_listed(self) -> Self:
        # `remove` cuts the file, so the two chapter-only categories aren't available for it.
        allowed = REMOVE_CATEGORIES if self.mode == "remove" else MARK_CATEGORIES
        for category in self.categories:
            if category not in allowed:
                raise ValueError(f"{category!r} is not a SponsorBlock category")
        return self

    def chosen(self) -> tuple[str, ...]:
        """The categories to send, filling in the mode's default when none were picked."""
        if self.categories:
            return self.categories
        return DEFAULT_MARK if self.mode == "mark" else DEFAULT_REMOVE


class DownloadOptions(BaseModel):
    """The only way options reach the command builder. Unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    quality: Quality
    container: Container = "mkv"
    fragments: Literal["auto"] | Annotated[int, Field(ge=1, le=16)] = "auto"
    use_aria2c: Literal["auto"] | bool = "auto"
    retries: Annotated[int, Field(ge=0)] = 5
    # Off unless the user picks a profile: a download never transcodes by itself (§5 step 2d).
    transcode: TranscodeProfile = TranscodeProfile.OFF
    # None means "use the stored default for this profile"; the scales differ per profile (§4.1).
    transcode_quality: Annotated[int, Field(ge=QUALITY_MIN, le=QUALITY_MAX)] | None = None
    subtitles: SubtitleOptions = SubtitleOptions()
    sponsorblock: SponsorBlockOptions = SponsorBlockOptions()
    #: A specific audio track from the inspection's `audio_tracks`; None is yt-dlp's best.
    audio_language: str | None = None
    video_codec: VideoCodec = "any"
    allow_hdr: bool = True
    rate_limit: str | None = None
    # On, as in download_video.sh; turning either off only drops its flag.
    embed_metadata: bool = True
    embed_chapters: bool = True

    @field_validator("audio_language", mode="after")
    @classmethod
    def _audio_language_is_a_language_tag(cls, language: str | None) -> str | None:
        if language is not None and not _LANGUAGE.match(language):
            raise ValueError(f"{language!r} is not a language code")
        return language

    @field_validator("rate_limit", mode="after")
    @classmethod
    def _rate_limit_is_a_rate(cls, rate: str | None) -> str | None:
        if rate is not None and not _RATE.match(rate):
            raise ValueError(f"{rate!r} is not a rate like 500K, 5M or 1.5M")
        return rate
