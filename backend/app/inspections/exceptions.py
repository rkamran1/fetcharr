class InspectError(Exception):
    """An inspect failure, carrying the HTTP status and body fields the router returns."""

    def __init__(
        self, status: int, detail: str, needs_cookies: bool = False, site_key: str | None = None
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.needs_cookies = needs_cookies
        #: The site the URL belongs to, so the UI can link to its cookies (§8).
        self.site_key = site_key
