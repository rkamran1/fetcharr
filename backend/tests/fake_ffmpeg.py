"""A stub `ffmpeg` on PATH, so the transcode step's failure paths are deterministic.

The same idea as `tests/fake_ytdlp.py`: it records every argv (and the `LIBVA_DRIVER_NAME` it
saw), emits real `-progress` blocks, and can fail for one encoder, block on a gate, or hang
after spawning a grandchild so the process-group kill has something to prove.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

_STUB = """#!{python}
import json, os, shutil, subprocess, sys, time

argv = sys.argv[1:]
with open(os.environ["FAKE_FFMPEG_CALLS"], "a") as calls:
    calls.write(json.dumps({{
        "argv": argv,
        "driver": os.environ.get("LIBVA_DRIVER_NAME"),
    }}) + "\\n")

events = os.environ["FAKE_FFMPEG_EVENTS"]


def record(what):
    with open(events, "a") as handle:
        handle.write(f"{{what}} {{os.getpid()}} {{time.time()}}\\n")


record("start")

if os.environ.get("FAKE_FFMPEG_SPAWN"):
    child = subprocess.Popen(["sleep", "60"])
    with open(os.environ["FAKE_FFMPEG_PIDS"], "w") as pids:
        pids.write(f"{{os.getpid()}} {{child.pid}}")
    time.sleep(60)

delay = float(os.environ.get("FAKE_FFMPEG_DELAY", "0"))
blocks = int(os.environ.get("FAKE_FFMPEG_PROGRESS", "3"))
for step in range(1, blocks + 1):
    print("frame=%d" % (step * 10), flush=True)
    print("out_time_us=%d" % (step * 600000), flush=True)
    print("progress=continue", flush=True)
    if delay:
        time.sleep(delay)

gate = os.environ.get("FAKE_FFMPEG_GATE")
if gate:
    while not os.path.exists(gate):
        time.sleep(0.02)

fail_for = os.environ.get("FAKE_FFMPEG_FAIL_FOR")
code = int(os.environ.get("FAKE_FFMPEG_EXIT", "0"))
if fail_for:
    code = 1 if any(fail_for in arg for arg in argv) else 0

if code:
    sys.stderr.write("fake ffmpeg: encoder unavailable\\n")
    sys.stderr.flush()
    record("end")
    sys.exit(code)

output = argv[-1]
# The hardware probe throws its output away with `-f null -`; there is nothing to write.
if not output.startswith("-"):
    media = os.environ.get("FAKE_FFMPEG_MEDIA")
    if media:
        shutil.copy(media, output)
    else:
        with open(output, "wb") as handle:
            handle.write(b"transcoded" * 1000)
print("progress=end", flush=True)
record("end")
sys.exit(0)
"""


class FakeFfmpeg:
    def __init__(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._monkeypatch = monkeypatch
        self._calls = root / "calls.jsonl"
        self._events = root / "events"
        self.pids_file = root / "pids"
        monkeypatch.setenv("FAKE_FFMPEG_CALLS", str(self._calls))
        monkeypatch.setenv("FAKE_FFMPEG_EVENTS", str(self._events))
        monkeypatch.setenv("FAKE_FFMPEG_PIDS", str(self.pids_file))
        self.transcodes()

    def transcodes(
        self,
        media: Path | None = None,
        *,
        progress_blocks: int = 3,
        delay: float = 0.0,
        gate: Path | None = None,
        exit_code: int = 0,
        fail_for: str | None = None,
        spawn_child: bool = False,
    ) -> None:
        """Behave like a real transcode: progress blocks, then a file (or a failure)."""
        self._monkeypatch.setenv("FAKE_FFMPEG_PROGRESS", str(progress_blocks))
        self._monkeypatch.setenv("FAKE_FFMPEG_DELAY", str(delay))
        self._monkeypatch.setenv("FAKE_FFMPEG_EXIT", str(exit_code))
        for name, value in (
            ("FAKE_FFMPEG_MEDIA", media),
            ("FAKE_FFMPEG_GATE", gate),
            ("FAKE_FFMPEG_FAIL_FOR", fail_for),
            ("FAKE_FFMPEG_SPAWN", "1" if spawn_child else None),
        ):
            if value is None:
                self._monkeypatch.delenv(name, raising=False)
            else:
                self._monkeypatch.setenv(name, str(value))

    def fails_for(self, encoder: str, media: Path | None = None) -> None:
        """Only this encoder fails, so the x265 fallback is the one that finishes (§6.1)."""
        self.transcodes(media, fail_for=encoder)

    def always_fails(self) -> None:
        self.transcodes(exit_code=1)

    def hangs(self) -> None:
        self.transcodes(spawn_child=True)

    @property
    def calls(self) -> list[list[str]]:
        return [call["argv"] for call in self._recorded]

    @property
    def drivers(self) -> list[str | None]:
        """The `LIBVA_DRIVER_NAME` each run saw, so the setting is proven to reach ffmpeg."""
        return [call["driver"] for call in self._recorded]

    @property
    def _recorded(self) -> list[dict[str, Any]]:
        if not self._calls.exists():
            return []
        return [json.loads(line) for line in self._calls.read_text().splitlines()]

    @property
    def max_concurrent(self) -> int:
        """The most stub processes that ran at once (the transcode semaphore, §6.1)."""
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
def fake_ffmpeg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, media: dict[str, Path]
) -> FakeFfmpeg:
    """Put a stub `ffmpeg` first on PATH. `media` first, so the clips are built for real."""
    assert media  # noqa: S101 - the fixture only has to have run before PATH is patched
    root = tmp_path / "fake-ffmpeg"
    bin_dir = root / "bin"
    bin_dir.mkdir(parents=True)
    stub = bin_dir / "ffmpeg"
    stub.write_text(_STUB.format(python=sys.executable))
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    return FakeFfmpeg(root, monkeypatch)
