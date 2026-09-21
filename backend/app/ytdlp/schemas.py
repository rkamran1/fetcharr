"""The allow-listed yt-dlp download options (requirements §4)."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.transcode.profiles import QUALITY_MAX, QUALITY_MIN, TranscodeProfile

Quality = Literal["144p", "240p", "360p", "480p", "720p", "1080p", "1440p", "2160p", "4k", "best"]
Container = Literal["mkv", "mp4"]


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
