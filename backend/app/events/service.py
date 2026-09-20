"""The in-memory progress snapshot and event fan-out behind `GET /api/events` (§3.1, §6)."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from app.events.schemas import Event, EventType, ProgressSnapshot

#: Dropped events would desync the UI, so a slow subscriber gets a generous buffer.
QUEUE_SIZE = 1000


class EventHub:
    """Live job state: one snapshot per job plus a queue per connected browser."""

    def __init__(self) -> None:
        self._progress: dict[str, ProgressSnapshot] = {}
        self._subscribers: set[asyncio.Queue[Event]] = set()

    def publish(self, type: EventType, data: dict[str, Any]) -> None:
        event = Event(type=type, data=data)
        if type == "job.progress":
            self._progress[str(data["job_id"])] = ProgressSnapshot(**data)
        for queue in self._subscribers:
            # A subscriber that can't keep up loses the event rather than the whole stream.
            if not queue.full():
                queue.put_nowait(event)

    def snapshot(self, job_id: str) -> ProgressSnapshot | None:
        """The live progress of a running job, for the API to overlay on the stored row."""
        return self._progress.get(job_id)

    def forget(self, job_id: str) -> None:
        self._progress.pop(job_id, None)

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[Event]]:
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)
