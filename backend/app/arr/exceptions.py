class ArrDomainError(Exception):
    """An arr lookup the router turns into an HTTP error."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


class RadarrNotConfigured(ArrDomainError):
    def __init__(self) -> None:
        super().__init__(400, "Radarr is not configured in Settings")


class RadarrUnavailable(ArrDomainError):
    def __init__(self, detail: str) -> None:
        super().__init__(502, detail)
