class SiteError(Exception):
    """A sites failure, carrying the HTTP status and message the router returns."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


class SiteNotFound(SiteError):
    def __init__(self, key: str) -> None:
        super().__init__(404, f"no site called {key!r}")


class SiteExists(SiteError):
    def __init__(self, key: str) -> None:
        super().__init__(409, f"a site called {key!r} already exists")


class BuiltinSite(SiteError):
    def __init__(self, key: str) -> None:
        super().__init__(409, f"{key!r} is built in and can't be deleted")


class InvalidCookies(SiteError):
    def __init__(self, detail: str) -> None:
        super().__init__(422, detail)
