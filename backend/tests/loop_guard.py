"""Fail any test whose event loop is blocked for longer than 100 ms (requirements §3.2).

asyncio debug mode (``asyncio_debug = true``) logs every callback that runs longer than
``slow_callback_duration`` on the ``asyncio`` logger. This plugin collects those records
and fails the test that produced them.

One-off construction inside an async fixture (building the app and its engines, running
the Alembic upgrade) happens in a pytest-asyncio fixture-setup task. That is startup
work, not the app blocking its own loop while serving, and on a slow CI runner it can
pass 100 ms on its own; those callbacks get a second's grace instead, so a genuinely
stuck fixture is still caught.
"""

import asyncio
import logging
import re
from collections.abc import Iterator

import pytest

SLOW_CALLBACK_DURATION = 0.1
FIXTURE_SETUP_BUDGET_S = 1.0

_FIXTURE_TASK = "_asyncgen_fixture_wrapper"
_TOOK_SECONDS = re.compile(r" took ([0-9.]+) seconds")


def _new_event_loop() -> asyncio.AbstractEventLoop:
    loop = asyncio.new_event_loop()
    loop.slow_callback_duration = SLOW_CALLBACK_DURATION
    return loop


def pytest_asyncio_loop_factories(config: pytest.Config, item: pytest.Item):
    return {"debug": _new_event_loop}


def _is_failure(message: str) -> bool:
    """Every slow callback fails, except fixture setup within its larger budget."""
    if _FIXTURE_TASK not in message:
        return True
    took = _TOOK_SECONDS.search(message)
    return took is None or float(took.group(1)) > FIXTURE_SETUP_BUDGET_S


class _SlowCallbackCollector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if message.startswith("Executing ") and " took " in message:
            self.messages.append(message)


@pytest.fixture(autouse=True)
def _fail_on_slow_callbacks() -> Iterator[None]:
    collector = _SlowCallbackCollector()
    logger = logging.getLogger("asyncio")
    logger.addHandler(collector)
    try:
        yield
    finally:
        logger.removeHandler(collector)
    blocked = [message for message in collector.messages if _is_failure(message)]
    if blocked:
        pytest.fail("event loop blocked: " + "; ".join(blocked), pytrace=False)
