"""A stub `yt-dlp` on PATH that replays recorded fixtures, so tests never touch the internet."""

import json
import os
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "ytdlp" / "fixtures"

_STUB = """#!{python}
import json, os, subprocess, sys, time

with open(os.environ["FAKE_YTDLP_CALLS"], "a") as calls:
    calls.write(json.dumps(sys.argv[1:]) + "\\n")

mode = os.environ["FAKE_YTDLP_MODE"]
if mode == "hang":
    child = subprocess.Popen(["sleep", "60"])
    with open(os.environ["FAKE_YTDLP_PIDS"], "w") as pids:
        pids.write(f"{{os.getpid()}} {{child.pid}}")
    time.sleep(60)
with open(os.environ["FAKE_YTDLP_FIXTURE"]) as fixture:
    data = fixture.read()
if mode == "json":
    sys.stdout.write(data)
    sys.exit(0)
sys.stderr.write(data)
sys.exit(1)
"""


class FakeYtdlp:
    def __init__(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._monkeypatch = monkeypatch
        self._calls = root / "calls.jsonl"
        self.pids_file = root / "pids"
        monkeypatch.setenv("FAKE_YTDLP_CALLS", str(self._calls))
        monkeypatch.setenv("FAKE_YTDLP_PIDS", str(self.pids_file))
        self.returns_json("youtube.json")

    def returns_json(self, name: str) -> None:
        self._monkeypatch.setenv("FAKE_YTDLP_MODE", "json")
        self._monkeypatch.setenv("FAKE_YTDLP_FIXTURE", str(FIXTURES / name))

    def fails_with(self, name: str) -> None:
        self._monkeypatch.setenv("FAKE_YTDLP_MODE", "fail")
        self._monkeypatch.setenv("FAKE_YTDLP_FIXTURE", str(FIXTURES / "stderr" / name))

    def hangs(self) -> None:
        self._monkeypatch.setenv("FAKE_YTDLP_MODE", "hang")

    @property
    def calls(self) -> list[list[str]]:
        if not self._calls.exists():
            return []
        return [json.loads(line) for line in self._calls.read_text().splitlines()]

    def pids(self) -> list[int]:
        return [int(pid) for pid in self.pids_file.read_text().split()]


@pytest.fixture
def fake_ytdlp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeYtdlp:
    """Put a stub `yt-dlp` first on PATH; it records every argv it's called with."""
    root = tmp_path / "fake-ytdlp"
    bin_dir = root / "bin"
    bin_dir.mkdir(parents=True)
    stub = bin_dir / "yt-dlp"
    stub.write_text(_STUB.format(python=sys.executable))
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    return FakeYtdlp(root, monkeypatch)
