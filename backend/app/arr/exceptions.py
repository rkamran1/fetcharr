class ArrDomainError(Exception):
    """An arr lookup the router turns into an HTTP error."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


class ArrNotConfigured(ArrDomainError):
    def __init__(self, app: str) -> None:
        super().__init__(400, f"{app} is not configured in Settings")


class ArrUnavailable(ArrDomainError):
    def __init__(self, detail: str) -> None:
        super().__init__(502, detail)


class RadarrNotConfigured(ArrNotConfigured):
    def __init__(self) -> None:
        super().__init__("Radarr")


class RadarrUnavailable(ArrUnavailable):
    pass


class SonarrNotConfigured(ArrNotConfigured):
    def __init__(self) -> None:
        super().__init__("Sonarr")


class SonarrUnavailable(ArrUnavailable):
    pass
