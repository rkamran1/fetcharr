class PresetError(Exception):
    """A presets failure, carrying the HTTP status and message the router returns."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


class PresetNotFound(PresetError):
    def __init__(self, preset_id: int) -> None:
        super().__init__(404, f"no preset with id {preset_id}")
