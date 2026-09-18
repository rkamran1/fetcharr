from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]

TEST_BLOCKING = """
import time

async def test_blocks_the_loop():
    time.sleep(0.2)
"""

TEST_AWAITING = """
import asyncio

async def test_awaits():
    await asyncio.sleep(0.2)
"""


def _run(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, source: str
) -> pytest.RunResult:
    monkeypatch.setenv("PYTHONPATH", str(BACKEND_DIR))
    pytester.makepyfile(source)
    return pytester.runpytest_subprocess(
        "-p",
        "tests.loop_guard",
        "-o",
        "asyncio_mode=auto",
        "-o",
        "asyncio_debug=true",
        "-o",
        "asyncio_default_fixture_loop_scope=function",
    )


def test_blocking_coroutine_fails(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _run(pytester, monkeypatch, TEST_BLOCKING)
    result.assert_outcomes(passed=1, errors=1)
    result.stdout.fnmatch_lines(["*event loop blocked: Executing*took 0.2*seconds*"])


def test_non_blocking_coroutine_passes(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _run(pytester, monkeypatch, TEST_AWAITING)
    result.assert_outcomes(passed=1)
