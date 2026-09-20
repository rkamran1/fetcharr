"""The job lifecycle vocabulary (requirements §6, §6.1, §10)."""

from enum import StrEnum


class JobStatus(StrEnum):
    QUEUED = "queued"
    STARTING = "starting"
    DOWNLOADING = "downloading"
    POSTPROCESSING = "postprocessing"
    TRANSCODING = "transcoding"
    ORGANIZING = "organizing"
    IMPORTING = "importing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Step(StrEnum):
    DOWNLOAD = "download"
    TRANSCODE = "transcode"
    ORGANIZE = "organize"
    IMPORT = "import"


class ImportStatus(StrEnum):
    NOT_APPLICABLE = "n/a"
    PENDING = "pending"
    IMPORTED = "imported"
    NOT_IMPORTED = "not_imported"
    ERROR = "error"


STEPS = (Step.DOWNLOAD, Step.TRANSCODE, Step.ORGANIZE, Step.IMPORT)

#: A job the JobManager still owns; a restart resumes or fails these (§6.1).
ACTIVE_STATUSES = (
    JobStatus.STARTING,
    JobStatus.DOWNLOADING,
    JobStatus.POSTPROCESSING,
    JobStatus.TRANSCODING,
    JobStatus.ORGANIZING,
    JobStatus.IMPORTING,
)

#: Cancel is only possible before the organize step starts (§6.1).
CANCELLABLE_STATUSES = (
    JobStatus.QUEUED,
    JobStatus.STARTING,
    JobStatus.DOWNLOADING,
    JobStatus.POSTPROCESSING,
    JobStatus.TRANSCODING,
)

TERMINAL_STATUSES = (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)
