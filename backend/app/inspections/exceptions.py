class InspectError(Exception):
    """An inspect failure, carrying the HTTP status and body fields the router returns."""

    def __init__(self, status: int, detail: str, needs_cookies: bool = False) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.needs_cookies = needs_cookies
