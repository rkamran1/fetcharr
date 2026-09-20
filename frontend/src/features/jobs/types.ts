export type JobStatus =
  | 'queued'
  | 'starting'
  | 'downloading'
  | 'postprocessing'
  | 'transcoding'
  | 'organizing'
  | 'importing'
  | 'completed'
  | 'failed'
  | 'cancelled'

export type Job = {
  id: string
  request_id: string
  url: string
  source_title: string | null
  thumbnail_url: string | null
  duration: number | null
  status: JobStatus
  phase: string | null
  attempt: number
  progress_pct: number | null
  downloaded_bytes: number | null
  total_bytes: number | null
  speed_bps: number | null
  eta_s: number | null
  completed_path: string | null
  file_size: number | null
  import_status: string
  error_code: string | null
  error_message: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export type JobList = { jobs: Job[] }
export type LogLine = { ts: string; level: string; line: string }
export type JobLog = { lines: LogLine[] }

/** The `job.progress` SSE payload: the live fields, straight from memory. */
export type ProgressEvent = {
  job_id: string
  progress_pct: number | null
  downloaded_bytes: number | null
  total_bytes: number | null
  speed_bps: number | null
  eta_s: number | null
}

/** The `job.state` SSE payload: what changed when a job moved on. */
export type StateEvent = {
  job_id: string
  status: JobStatus
  phase: string | null
  completed_path?: string | null
  error_message?: string | null
  finished_at?: string | null
}
