"""Fail any test whose event loop is blocked for longer than 100 ms (requirements §3.2).

asyncio debug mode (``asyncio_debug = true``) logs every callback that runs longer than
``slow_callback_duration`` on the ``asyncio`` logger. This plugin collects those records
and fails the test that produced them.
"""

import asyncio
import logging
from collections.abc import Iterator

import pytest

SLOW_CALLBACK_DURATION = 0.1


def _new_event_loop() -> asyncio.AbstractEventLoop:
    loop = asyncio.new_event_loop()
    loop.slow_callback_duration = SLOW_CALLBACK_DURATION
    return loop


def pytest_asyncio_loop_factories(config: pytest.Config, item: pytest.Item):
    return {"debug": _new_event_loop}


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
    if collector.messages:
        pytest.fail("event loop blocked: " + "; ".join(collector.messages), pytrace=False)
