import gc
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

# Construction inside an async fixture: slow, but not the app blocking its own loop.
TEST_SLOW_FIXTURE = """
import asyncio, time
import pytest

@pytest.fixture
async def built():
    time.sleep(0.2)
    await asyncio.sleep(0)
    yield "app"

async def test_uses_it(built):
    assert built == "app"
"""

# A test body blocking for far longer than any runner stall could explain.
TEST_STUCK_BODY = """
import time

async def test_blocks_the_loop_badly():
    time.sleep(1.2)
"""

# The same fixture, stuck for far longer than any construction should take.
TEST_STUCK_FIXTURE = """
import asyncio, time
import pytest

@pytest.fixture
async def stuck():
    time.sleep(1.2)
    await asyncio.sleep(0)
    yield "app"

async def test_uses_it(stuck):
    assert stuck == "app"
"""


def _run(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    budget: str = "0.1",
) -> pytest.RunResult:
    monkeypatch.setenv("PYTHONPATH", str(BACKEND_DIR))
    # Pinned, so these tests assert the same thing on a laptop and on CI, where the
    # default test budget is relaxed for runner jitter.
    monkeypatch.setenv("LOOP_GUARD_TEST_BUDGET_S", budget)
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


def test_slow_fixture_setup_is_tolerated(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Building the app and migrating the database costs more than 100 ms on CI (M5a)."""
    result = _run(pytester, monkeypatch, TEST_SLOW_FIXTURE)
    result.assert_outcomes(passed=1)


def test_stuck_fixture_setup_still_fails(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _run(pytester, monkeypatch, TEST_STUCK_FIXTURE)
    result.assert_outcomes(passed=1, errors=1)
    result.stdout.fnmatch_lines(["*event loop blocked: Executing*took 1.2*seconds*"])


def test_a_raised_budget_tolerates_runner_jitter(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What CI uses: a stall a little over 100 ms is the runner, not the app (M5c)."""
    result = _run(pytester, monkeypatch, TEST_BLOCKING, budget="0.5")

    result.assert_outcomes(passed=1)


def test_a_raised_budget_still_catches_real_blocking(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The relaxed budget is headroom, not an off switch: 1.2 s is still a failure."""
    result = _run(pytester, monkeypatch, TEST_STUCK_BODY, budget="0.5")

    result.assert_outcomes(passed=1, errors=1)
    result.stdout.fnmatch_lines(["*event loop blocked: Executing*took 1.2*seconds*"])


def test_collected_objects_are_frozen_out_of_the_collector() -> None:
    """A gen-2 collection mid-test doesn't walk the session's own objects (M9)."""
    assert gc.get_freeze_count() > 10_000
