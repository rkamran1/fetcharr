"""The Intel QSV/VAAPI self-test behind `/api/system/status` (requirements §11, §13.1).

Two halves, because they cost very different things. `device_report` is a stat call and runs
at startup, so the status page can always say whether the iGPU was passed through at all.
`check_hardware` additionally runs `vainfo` and a one-second encode per hardware profile, and
runs only when someone presses **Test hardware encode** in Settings.
"""

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path

from app.transcode.profiles import (
    BASE_ARGS,
    DEFAULT_QUALITY,
    HARDWARE,
    RENDER_DEVICE,
    TranscodeProfile,
    input_args,
    video_args,
)

#: One second of colour bars is enough to prove the encoder initialises (§13.1).
PROBE_INPUT = ["-f", "lavfi", "-i", "testsrc=size=640x360:rate=25:duration=1"]
#: vainfo prints one line per profile/entrypoint pair; this is the one that matters (§13.1).
HEVC_PROFILE = "VAProfileHEVCMain"
ENCODE_ENTRYPOINT = "VAEntrypointEncSlice"

NOT_CHECKED = "not checked yet"
PASS_THROUGH_HINT = "pass the iGPU through with `devices: - /dev/dri:/dev/dri`"
GROUP_HINT = 'add the render group with `group_add: - "$(getent group render | cut -d: -f3)"`'


@dataclass(frozen=True)
class ProfileCheck:
    """One hardware profile's one-second test encode."""

    profile: str
    ok: bool
    error: str | None = None


@dataclass(frozen=True)
class TranscodeReport:
    """What Settings and `/api/system/status` show about the hardware encoder (§11)."""

    device: bool
    device_path: str
    #: True once a full self-test has run; the startup check only looks at the device.
    tested: bool
    hevc_encode: bool
    ok: bool
    message: str
    profiles: tuple[ProfileCheck, ...] = ()


def device_report(device: Path = RENDER_DEVICE) -> TranscodeReport:
    """The cheap half, run at startup: is the render node there, and can we open it?"""
    if not device.exists():
        return _no_hardware(device, f"{device} is not present: {PASS_THROUGH_HINT}", tested=False)
    if not os.access(device, os.R_OK | os.W_OK):
        return _no_hardware(device, f"{device} is not accessible: {GROUP_HINT}", tested=False)
    return TranscodeReport(
        device=True,
        device_path=str(device),
        tested=False,
        hevc_encode=False,
        ok=False,
        message=f"{device} found; run the hardware encode test",
    )


def unknown(device: Path = RENDER_DEVICE) -> TranscodeReport:
    return _no_hardware(device, NOT_CHECKED, tested=False)


def _no_hardware(device: Path, message: str, *, tested: bool = True) -> TranscodeReport:
    return TranscodeReport(
        device=False,
        device_path=str(device),
        tested=tested,
        hevc_encode=False,
        ok=False,
        message=message,
    )


async def check_hardware(
    device: Path = RENDER_DEVICE, driver: str = "iHD", binary: str = "ffmpeg"
) -> TranscodeReport:
    """The full self-test: the device, `vainfo`'s HEVC entrypoints, then a test encode each."""
    found = await asyncio.to_thread(device_report, device)
    if not found.device:
        # No GPU passed through, so there is nothing to ask vainfo or ffmpeg about.
        return _no_hardware(device, found.message)

    hevc_encode = await _vainfo_has_hevc_encode(driver)
    checks = tuple([await _probe(profile, driver, binary) for profile in HARDWARE])
    ok = any(check.ok for check in checks)
    working = ", ".join(check.profile for check in checks if check.ok)
    return TranscodeReport(
        device=True,
        device_path=str(device),
        tested=True,
        hevc_encode=hevc_encode,
        ok=ok,
        message=f"hardware encode works with {working}" if ok else "no hardware profile encoded",
        profiles=checks,
    )


def probe_argv(profile: TranscodeProfile) -> list[str]:
    """A one-second `testsrc` encode, thrown away: it only has to initialise (§13.1)."""
    return [
        *BASE_ARGS,
        *input_args(profile),
        *PROBE_INPUT,
        *video_args(profile, DEFAULT_QUALITY[profile]),
        "-f",
        "null",
        "-",
    ]


async def _probe(profile: TranscodeProfile, driver: str, binary: str) -> ProfileCheck:
    code, output = await _run(binary, probe_argv(profile), driver)
    if code == 0:
        return ProfileCheck(profile=str(profile), ok=True)
    return ProfileCheck(profile=str(profile), ok=False, error=_last_line(output) or f"exit {code}")


async def _vainfo_has_hevc_encode(driver: str) -> bool:
    code, output = await _run("vainfo", [], driver)
    if code != 0:
        return False
    return any(HEVC_PROFILE in line and ENCODE_ENTRYPOINT in line for line in output.splitlines())


async def _run(binary: str, argv: list[str], driver: str) -> tuple[int, str]:
    """Run one short tool, never through a shell, with libva pointed at the right driver."""
    try:
        process = await asyncio.create_subprocess_exec(
            binary,
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
            env={**os.environ, "LIBVA_DRIVER_NAME": driver},
        )
    except OSError as error:
        return 127, str(error)
    stdout, _ = await process.communicate()
    return process.returncode or 0, stdout.decode(errors="replace")


def _last_line(output: str) -> str:
    for line in reversed(output.splitlines()):
        if line.strip():
            return line.strip()
    return ""


class HardwareStatus:
    """The last self-test. Long-lived on `app.state`, like the arr clients (§6.1)."""

    def __init__(self, device: Path = RENDER_DEVICE, driver: str = "iHD") -> None:
        self.device = device
        self.driver = driver
        self.report = unknown(device)

    async def start(self) -> None:
        """Startup: the device check only, so no ffmpeg runs before the app accepts jobs."""
        self.report = await asyncio.to_thread(device_report, self.device)

    async def refresh(self) -> TranscodeReport:
        """What the Settings button runs: the full check, including the test encodes."""
        self.report = await check_hardware(self.device, self.driver)
        return self.report
