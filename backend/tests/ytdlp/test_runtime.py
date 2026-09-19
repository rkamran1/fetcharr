import os
from pathlib import Path

import pytest

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
