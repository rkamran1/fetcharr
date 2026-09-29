import os
from pathlib import Path

import pytest

from app.ytdlp import runtime
from app.ytdlp.runtime import detect_js_runtime


def _bin_dir(root: Path, *names: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name in names:
        exe = root / name
        exe.write_text("#!/bin/sh\n")
        exe.chmod(0o755)
    return root


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home


def test_prefers_deno(tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(_bin_dir(tmp_path / "bin", "deno", "node")))

    assert detect_js_runtime() == "deno"


def test_falls_back_to_node(tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(_bin_dir(tmp_path / "bin", "node")))

    assert detect_js_runtime() == "node"


def test_returns_none_without_runtime(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(_bin_dir(tmp_path / "bin")))

    assert detect_js_runtime() is None


def test_finds_deno_in_home_deno_bin(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path_dir = _bin_dir(tmp_path / "bin", "node")
    deno_dir = _bin_dir(home / ".deno" / "bin", "deno")
    monkeypatch.setenv("PATH", str(path_dir))

    assert detect_js_runtime() == "deno"
    assert Path(os.environ["PATH"].split(os.pathsep)[0]) == deno_dir


def _stub(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(0o755)
    return path


@pytest.fixture
def venv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A stand-in for /opt/yt-dlp, with a pip and a yt-dlp that record what they were given."""
    root = tmp_path / "opt" / "yt-dlp"
    monkeypatch.setattr(runtime, "YTDLP_PIP", root / "bin" / "pip")
    monkeypatch.setattr(runtime, "YTDLP_BIN", root / "bin" / "yt-dlp")
    return root


def test_pip_path_is_inside_the_ytdlp_venv() -> None:
    assert runtime.YTDLP_VENV == Path("/opt/yt-dlp")
    assert runtime.YTDLP_PIP == Path("/opt/yt-dlp/bin/pip")
    assert runtime.YTDLP_BIN == Path("/opt/yt-dlp/bin/yt-dlp")


async def test_update_argv_is_pip_install_upgrade(venv: Path) -> None:
    calls = venv / "calls.txt"
    _stub(venv / "bin" / "pip", f'printf "%s\\n" "$0 $*" >> {calls}\necho "Successfully installed"')
    _stub(venv / "bin" / "yt-dlp", f'printf "%s\\n" "$0 $*" >> {calls}\necho 2026.09.01')

    await runtime.update_ytdlp()

    recorded = calls.read_text().splitlines()
    assert recorded[1] == f"{venv / 'bin' / 'pip'} install --upgrade yt-dlp"
    # Only the venv's own binaries are ever run.
    assert all(line.startswith(str(venv)) for line in recorded)


async def test_update_returns_old_and_new_version(venv: Path) -> None:
    marker = venv / "installed"
    _stub(venv / "bin" / "pip", f"touch {marker}\necho 'Successfully installed yt-dlp-2026.09.20'")
    _stub(
        venv / "bin" / "yt-dlp",
        f"if [ -f {marker} ]; then echo 2026.09.20; else echo 2026.09.01; fi",
    )

    result = await runtime.update_ytdlp()

    assert (result.old, result.new) == ("2026.09.01", "2026.09.20")
    assert "Successfully installed" in result.output


async def test_update_raises_on_pip_failure(venv: Path) -> None:
    _stub(venv / "bin" / "pip", "echo 'could not reach the index' >&2\nexit 1")
    _stub(venv / "bin" / "yt-dlp", "echo 2026.09.01")

    with pytest.raises(runtime.UpdateError, match="could not reach the index"):
        await runtime.update_ytdlp()


async def test_update_raises_when_pip_is_missing(venv: Path) -> None:
    _stub(venv / "bin" / "yt-dlp", "echo 2026.09.01")

    with pytest.raises(runtime.UpdateError):
        await runtime.update_ytdlp()


async def test_tool_versions_read_the_tools(
    venv: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub(venv / "bin" / "yt-dlp", "echo 2026.09.20")
    path_dir = tmp_path / "bin"
    _stub(path_dir / "ffmpeg", "echo 'ffmpeg version 7.1.1-1 Copyright (c) 2000-2025'")
    _stub(path_dir / "deno", "echo 'deno 2.1.4 (release, aarch64-apple-darwin)'")
    monkeypatch.setenv("PATH", str(path_dir))

    versions = await runtime.tool_versions()

    assert versions == runtime.ToolVersions(ytdlp="2026.09.20", ffmpeg="7.1.1-1", deno="2.1.4")


async def test_tool_versions_report_a_missing_tool_as_none(
    venv: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(_bin_dir(tmp_path / "empty")))

    versions = await runtime.tool_versions()

    assert versions == runtime.ToolVersions(ytdlp=None, ffmpeg=None, deno=None)
