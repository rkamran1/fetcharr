"""Normalise a `yt-dlp -J` result into the fields the UI and step 2 need (pure)."""

from typing import Any

from app.inspections.exceptions import InspectError
from app.ytdlp.schemas import DownloadOptions
from app.ytdlp.stream import classify, resolve_auto

PLAYLIST_MESSAGE = "Playlists aren't supported, paste a single video URL."


def _codec_family(codec: str) -> str:
    family = codec.split(".")[0]
    return "vp9" if family == "vp09" else family


def _size(fmt: dict[str, Any]) -> int | None:
    size = fmt.get("filesize") or fmt.get("filesize_approx")
    return int(size) if size else None


def _from_bitrate(fmt: dict[str, Any], duration: float | None) -> int | None:
    """yt-dlp's own approximation: the bitrate over the running time, in bytes.

    Muxed HLS and many progressive formats report no filesize at all, so without this
    only a couple of heights would ever show a size in the picker.
    """
    tbr = fmt.get("tbr")
    if not tbr or not duration:
        return None
    return int(float(tbr) * 1000 / 8 * float(duration))


def _has(fmt: dict[str, Any], key: str) -> bool:
    return fmt.get(key) not in (None, "none")


def _sub_exts(tracks: dict[str, list[dict[str, Any]]] | None) -> dict[str, list[str]]:
    return {
        lang: list(dict.fromkeys(t["ext"] for t in entries if t.get("ext")))
        for lang, entries in (tracks or {}).items()
    }


def _year(info: dict[str, Any]) -> int | None:
    if info.get("release_year"):
        return int(info["release_year"])
    for key in ("release_date", "upload_date"):
        value = info.get(key)
        if value and len(value) >= 4 and value[:4].isdigit():
            return int(value[:4])
    return None


def normalise(info: dict[str, Any], aria2c_available: bool) -> dict[str, Any]:
    """The fields the UI and step 2 need from a `-J` result. Rejects playlists."""
    if info.get("_type") == "playlist" or "entries" in info:
        raise InspectError(422, PLAYLIST_MESSAGE)

    formats: list[dict[str, Any]] = info.get("formats") or [info]
    video = [f for f in formats if _has(f, "vcodec") and f.get("height")]
    audio_only = [f for f in formats if _has(f, "acodec") and not _has(f, "vcodec")]
    audio_sources = audio_only or [f for f in formats if _has(f, "acodec")]

    tracks: dict[tuple[str | None, str, int | None], dict[str, Any]] = {}
    for f in audio_sources:
        abr = round(f["abr"]) if f.get("abr") else None
        key = (f.get("language"), _codec_family(f["acodec"]), abr)
        tracks[key] = {"lang": key[0], "codec": key[1], "abr": key[2]}

    duration = info.get("duration")
    best_audio = max((s for f in audio_only if (s := _size(f))), default=0)
    best_audio_guess = max(
        (s for f in audio_only if (s := _size(f) or _from_bitrate(f, duration))), default=0
    )
    # Reported sizes win; a bitrate estimate only fills a height nothing else covers.
    known: dict[int, int] = {}
    guessed: dict[int, int] = {}
    for f in video:
        height = f["height"]
        size = _size(f)
        if size is not None:
            if not _has(f, "acodec"):
                size += best_audio
            known[height] = max(known.get(height, 0), size)
            continue
        estimate = _from_bitrate(f, duration)
        if estimate is None:
            continue
        if not _has(f, "acodec"):
            estimate += best_audio_guess
        guessed[height] = max(guessed.get(height, 0), estimate)
    sizes: dict[int, int] = {h: known.get(h) or guessed[h] for h in {**guessed, **known}}

    stream_type = classify(info)
    resolved = resolve_auto(stream_type, DownloadOptions(quality="best"), aria2c_available)
    return {
        "title": info.get("title"),
        "uploader": info.get("uploader") or info.get("channel"),
        "thumbnail": info.get("thumbnail"),
        "duration": info.get("duration"),
        "webpage_url": info.get("webpage_url"),
        "extractor": info.get("extractor"),
        "id": info.get("id"),
        "upload_date": info.get("upload_date"),
        "release_year": _year(info),
        "video_heights": sorted({f["height"] for f in video}, reverse=True),
        "video_codecs": sorted({_codec_family(f["vcodec"]) for f in video}),
        "audio_tracks": sorted(
            tracks.values(), key=lambda t: (t["lang"] or "", t["codec"], -(t["abr"] or 0))
        ),
        "has_hdr": any(f.get("dynamic_range") not in (None, "SDR") for f in video),
        "subtitles": _sub_exts(info.get("subtitles")),
        "automatic_captions": _sub_exts(info.get("automatic_captions")),
        "estimated_sizes": {str(h): s for h, s in sorted(sizes.items(), reverse=True)},
        "stream_type": stream_type,
        "auto": {"fragments": resolved.fragments, "use_aria2c": resolved.use_aria2c},
    }
