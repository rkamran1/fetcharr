"""The allow-listed yt-dlp download options (requirements §4)."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

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
