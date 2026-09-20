class SetupAlreadyComplete(Exception):
    """The account exists already (409)."""


class InvalidCredentials(Exception):
    """Wrong username or password at login (401)."""


class RateLimited(Exception):
    """Too many login attempts from one client (429 with Retry-After)."""

    def __init__(self, retry_after: int) -> None:
        super().__init__(f"retry after {retry_after} s")
        self.retry_after = retry_after


class WrongPassword(Exception):
    """The current password given for a password change is wrong (400)."""
