from fastapi import Request

from app.events.service import EventHub


def get_event_hub(request: Request) -> EventHub:
    return request.app.state.hub
