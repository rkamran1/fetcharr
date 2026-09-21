"""A stub `yt-dlp` on PATH that replays recorded fixtures, so tests never touch the internet."""

import json
import os
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "ytdlp" / "fixtures"

_STUB = """#!{python}
import json, os, shutil, subprocess, sys, time

argv = sys.argv[1:]
with open(os.environ["FAKE_YTDLP_CALLS"], "a") as calls:
    calls.write(json.dumps(argv) + "\\n")

mode = os.environ["FAKE_YTDLP_MODE"]
events = os.environ.get("FAKE_YTDLP_EVENTS")


def record(what):
    if events:
        with open(events, "a") as handle:
            handle.write(f"{{what}} {{os.getpid()}} {{time.time()}}\\n")


def spawn_child():
    child = subprocess.Popen(["sleep", "60"])
    with open(os.environ["FAKE_YTDLP_PIDS"], "w") as pids:
        pids.write(f"{{os.getpid()}} {{child.pid}}")


if mode == "hang":
    spawn_child()
    time.sleep(60)

if mode == "download":
    record("start")
    # Where yt-dlp would write: the job dir holding the --print-to-file target.
    final_path_file = argv[argv.index("--print-to-file") + 2]
    job_dir = os.path.dirname(final_path_file)
    lines = int(os.environ.get("FAKE_YTDLP_PROGRESS", "3"))
    delay = float(os.environ.get("FAKE_YTDLP_DELAY", "0"))
    total = 10_000_000
    for step in range(1, lines + 1):
        print("FA_PROGRESS " + json.dumps({{
            "status": "downloading",
            "downloaded_bytes": int(total * step / lines),
            "total_bytes": total,
            "speed": 1_048_576.0,
            "eta": lines - step,
        }}), flush=True)
        if delay:
            time.sleep(delay)
    if os.environ.get("FAKE_YTDLP_SPAWN"):
        spawn_child()
        time.sleep(60)
    gate = os.environ.get("FAKE_YTDLP_GATE")
    if gate:
        while not os.path.exists(gate):
            time.sleep(0.02)
    stderr = os.environ.get("FAKE_YTDLP_STDERR")
    if stderr:
        sys.stderr.write(stderr + "\\n")
        sys.stderr.flush()
    code = int(os.environ.get("FAKE_YTDLP_EXIT", "0"))
    if code:
        record("end")
        sys.exit(code)
    # The container yt-dlp was told to remux into decides the file it leaves behind.
    container = argv[argv.index("--remux-video") + 1] if "--remux-video" in argv else "mkv"
    print('[Merger] Merging formats into "video.%s"' % container, flush=True)
    media = os.environ.get("FAKE_YTDLP_MEDIA")
    output = os.path.join(job_dir, "video." + container)
    if media:
        shutil.copy(media, output)
    else:
        with open(output, "wb") as handle:
            handle.write(b"video" * 1000)
    with open(final_path_file, "a") as handle:
        handle.write(output + "\\n")
    record("end")
    sys.exit(0)

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
        self._events = root / "events"
        self.pids_file = root / "pids"
        monkeypatch.setenv("FAKE_YTDLP_CALLS", str(self._calls))
        monkeypatch.setenv("FAKE_YTDLP_PIDS", str(self.pids_file))
        monkeypatch.setenv("FAKE_YTDLP_EVENTS", str(self._events))
        self.returns_json("youtube.json")

    def returns_json(self, name: str) -> None:
        self._monkeypatch.setenv("FAKE_YTDLP_MODE", "json")
        self._monkeypatch.setenv("FAKE_YTDLP_FIXTURE", str(FIXTURES / name))

    def fails_with(self, name: str) -> None:
        self._monkeypatch.setenv("FAKE_YTDLP_MODE", "fail")
        self._monkeypatch.setenv("FAKE_YTDLP_FIXTURE", str(FIXTURES / "stderr" / name))

    def hangs(self) -> None:
        self._monkeypatch.setenv("FAKE_YTDLP_MODE", "hang")

    def downloads(
        self,
        media: Path | None = None,
        *,
        progress_lines: int = 3,
        delay: float = 0.0,
        exit_code: int = 0,
        stderr: str | None = None,
        gate: Path | None = None,
        spawn_child: bool = False,
    ) -> None:
        """Behave like a real download: progress lines, then a file (or a failure)."""
        self._monkeypatch.setenv("FAKE_YTDLP_MODE", "download")
        self._monkeypatch.setenv("FAKE_YTDLP_PROGRESS", str(progress_lines))
        self._monkeypatch.setenv("FAKE_YTDLP_DELAY", str(delay))
        self._monkeypatch.setenv("FAKE_YTDLP_EXIT", str(exit_code))
        for name, value in (
            ("FAKE_YTDLP_MEDIA", media),
            ("FAKE_YTDLP_STDERR", stderr),
            ("FAKE_YTDLP_GATE", gate),
            ("FAKE_YTDLP_SPAWN", "1" if spawn_child else None),
        ):
            if value is None:
                self._monkeypatch.delenv(name, raising=False)
            else:
                self._monkeypatch.setenv(name, str(value))

    @property
    def calls(self) -> list[list[str]]:
        if not self._calls.exists():
            return []
        return [json.loads(line) for line in self._calls.read_text().splitlines()]

    @property
    def max_concurrent(self) -> int:
        """The most stub processes that ran at the same time (the download semaphore)."""
        if not self._events.exists():
            return 0
        marks = sorted(
            (float(parts[2]), 1 if parts[0] == "start" else -1)
            for parts in (line.split() for line in self._events.read_text().splitlines())
        )
        running = 0
        highest = 0
        for _timestamp, delta in marks:
            running += delta
            highest = max(highest, running)
        return highest

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
