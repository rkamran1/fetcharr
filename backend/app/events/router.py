"""The SSE stream every browser listens on (requirements §6, §11)."""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.events.dependencies import get_event_hub
from app.events.service import EventHub

router = APIRouter(prefix="/api", tags=["events"])

#: Proxies drop an idle connection, so send a comment line while nothing happens.
KEEPALIVE_S = 15.0


async def _stream(hub: EventHub) -> AsyncIterator[str]:
    async with hub.subscribe() as queue:
        yield ": connected\n\n"
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), KEEPALIVE_S)
            except TimeoutError:
                yield ": keep-alive\n\n"
                continue
            body = json.dumps(event.data, default=str)
            yield f"event: {event.type}\ndata: {body}\n\n"


@router.get("/events")
async def events(hub: Annotated[EventHub, Depends(get_event_hub)]) -> StreamingResponse:
    return StreamingResponse(
        _stream(hub),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
