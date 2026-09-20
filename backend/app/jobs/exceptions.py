class JobError(Exception):
    """A job operation the router turns into an HTTP error."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


class JobNotFound(JobError):
    def __init__(self, job_id: str) -> None:
        super().__init__(404, f"No job {job_id}")


class CancelTooLate(JobError):
    """Cancel is only possible before the organize step starts (requirements §6.1)."""

    def __init__(self, status_name: str) -> None:
        super().__init__(409, f"A job that is {status_name} can't be cancelled")


class RetryNotPossible(JobError):
    def __init__(self, status_name: str) -> None:
        super().__init__(409, f"Only a failed job can be retried; this one is {status_name}")


class UnsafePath(JobError):
    def __init__(self, path: str) -> None:
        super().__init__(400, f"{path} is outside the fetcharr folders")
