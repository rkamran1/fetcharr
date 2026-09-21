"""The QSV/VAAPI self-test (requirements §11, §13.1). No GPU here, so the device is faked."""

import asyncio
from pathlib import Path

from app.transcode.hwcheck import HardwareStatus, check_hardware, device_report, probe_argv
from app.transcode.profiles import TranscodeProfile
from tests.fake_ffmpeg import FakeFfmpeg
from tests.transcode.conftest import write


async def test_no_device_is_reported_cleanly(tmp_path: Path, fake_ffmpeg: FakeFfmpeg) -> None:
    """The Mac and CI case: nothing to test, said plainly, and no subprocess started."""
    missing = tmp_path / "dev" / "dri" / "renderD128"

    report = await check_hardware(missing)

    assert report.device is False
    assert report.ok is False
    assert report.tested is True
    assert report.profiles == ()
    assert str(missing) in report.message
    assert "devices: - /dev/dri:/dev/dri" in report.message
    assert fake_ffmpeg.calls == []


async def test_a_present_device_is_reported_untested(tmp_path: Path) -> None:
    """The startup half: the render node is there, but nothing has been encoded yet."""
    device = await asyncio.to_thread(write, tmp_path / "renderD128", "")

    report = await asyncio.to_thread(device_report, device)

    assert report.device is True
    assert report.tested is False
    assert report.ok is False
    assert "run the hardware encode test" in report.message


async def test_a_failing_profile_encode_is_reported(
    tmp_path: Path, fake_ffmpeg: FakeFfmpeg
) -> None:
    device = await asyncio.to_thread(write, tmp_path / "renderD128", "")
    fake_ffmpeg.fails_for("hevc_qsv")

    report = await check_hardware(device)

    assert report.tested is True
    assert [(check.profile, check.ok) for check in report.profiles] == [
        ("hevc-qsv", False),
        ("hevc-vaapi", True),
    ]
    qsv = report.profiles[0]
    assert qsv.error
    assert report.ok is True
    assert "hevc-vaapi" in report.message


async def test_a_passing_profile_encode_is_reported(
    tmp_path: Path, fake_ffmpeg: FakeFfmpeg
) -> None:
    device = await asyncio.to_thread(write, tmp_path / "renderD128", "")

    report = await check_hardware(device)

    assert report.ok is True
    assert all(check.ok for check in report.profiles)
    assert [check.error for check in report.profiles] == [None, None]


async def test_every_profile_failing_is_not_ok(tmp_path: Path, fake_ffmpeg: FakeFfmpeg) -> None:
    device = await asyncio.to_thread(write, tmp_path / "renderD128", "")
    fake_ffmpeg.always_fails()

    report = await check_hardware(device)

    assert report.ok is False
    assert report.message == "no hardware profile encoded"


def test_the_probe_is_one_second_of_test_bars() -> None:
    argv = probe_argv(TranscodeProfile.HEVC_QSV)

    assert "testsrc=size=640x360:rate=25:duration=1" in argv
    assert argv[-3:] == ["-f", "null", "-"]
    assert argv[argv.index("-c:v") + 1] == "hevc_qsv"


async def test_hardware_status_starts_cheap_then_refreshes(
    tmp_path: Path, fake_ffmpeg: FakeFfmpeg
) -> None:
    device = await asyncio.to_thread(write, tmp_path / "renderD128", "")
    status = HardwareStatus(device=device)

    assert status.report.tested is False
    assert status.report.message == "not checked yet"

    await status.start()
    assert status.report.device is True
    assert status.report.tested is False
    # Startup only stats the device: no encode has run (§13.1).
    assert fake_ffmpeg.calls == []

    refreshed = await status.refresh()
    assert refreshed.tested is True
    assert status.report is refreshed
    assert len(fake_ffmpeg.calls) == 2
