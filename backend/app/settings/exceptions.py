class SettingsError(Exception):
    """A settings failure the router turns into an HTTP error."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


class InvalidSetting(SettingsError):
    def __init__(self, detail: str) -> None:
        super().__init__(422, detail)
