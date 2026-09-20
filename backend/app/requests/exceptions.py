class RequestError(Exception):
    """A request failure the router turns into an HTTP error."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


class InspectionNotFound(RequestError):
    def __init__(self, inspection_id: int) -> None:
        super().__init__(404, f"Inspection {inspection_id} is unknown or has expired")


class RequestNotFound(RequestError):
    def __init__(self, request_id: str) -> None:
        super().__init__(404, f"No request {request_id}")


class UnnameableVideo(RequestError):
    def __init__(self, reason: str) -> None:
        super().__init__(422, reason)
