"""Saved option bundles (requirements §5 step 2d, §10, §11)."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from app.ytdlp.schemas import DownloadOptions

#: A preset for one wizard, or `any` to offer it in all of them.
PresetMediaType = Literal["movie", "tv", "other", "any"]
Name = Annotated[str, Field(min_length=1, max_length=80)]


class PresetCreate(BaseModel):
    model_config = {"extra": "forbid"}

    name: Name
    media_type: PresetMediaType = "any"
    #: Validated as real options, so a preset can never carry a flag the allow-list forbids.
    options: DownloadOptions
    is_default: bool = False


class PresetUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    name: Name | None = None
    media_type: PresetMediaType | None = None
    options: DownloadOptions | None = None
    is_default: bool | None = None


class PresetRead(BaseModel):
    id: int
    name: str
    media_type: str
    #: Read back loosely, so a preset saved before an option existed still renders.
    options: dict[str, Any]
    is_default: bool
