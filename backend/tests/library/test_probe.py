from pathlib import Path

import pytest

from app.library.naming import quality_label
from app.library.probe import ProbeError, probe


@pytest.mark.parametrize(
    ("fixture", "label"),
    [
        ("landscape", "WEBDL-1080p"),
        ("vertical", "WEBDL-1080p"),
        ("qhd", "WEBDL-1080p"),
        ("uhd", "WEBDL-2160p"),
        ("hd", "WEBDL-720p"),
        ("small", "WEBDL-480p"),
    ],
)
async def test_quality_from_real_probe(media: dict[str, Path], fixture: str, label: str) -> None:
    result = await probe(media[fixture])

    assert quality_label(result.width, result.height) == label


async def test_probe_reads_streams(media: dict[str, Path]) -> None:
    result = await probe(media["vertical"])

    assert (result.width, result.height) == (1080, 1920)
    assert result.vcodec == "mpeg4"
    assert result.acodec == "aac"
    assert result.duration > 0
    assert result.has_video

    audio = await probe(media["audio"])

    assert not audio.has_video
    assert audio.acodec == "aac"

    with pytest.raises(ProbeError):
        await probe(media["garbage"])
