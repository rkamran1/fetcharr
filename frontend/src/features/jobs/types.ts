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

export type ImportStatus = 'n/a' | 'pending' | 'imported' | 'not_imported' | 'error'

/** Radarr's own words: why it refused, or what went wrong asking it (§7.5). */
export type ImportDetail = {
  rejections?: string[]
  /** What a one-word rejection like "Sample" means for this file, measured by fetcharr. */
  explanation?: string
  error?: string
  hint?: string
}

export type Job = {
  id: string
  request_id: string
  /** The request this job belongs to, so the queue can group and name it (§12). */
  media_type: 'other' | 'movie' | 'tv'
  request_title: string | null
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
  /** True when a hardware transcode failed and x265 software finished it (§6.1). */
  transcode_fallback_used: boolean
  /** Which episode this is (tv only). */
  season: number | null
  episode: number | null
  episode_title: string | null
  air_date: string | null
  import_status: ImportStatus
  import_attempts: number
  import_detail: ImportDetail | null
  imported_path: string | null
  imported_at: string | null
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

/** The `job.import` SSE payload: how the Radarr import ended (§6). */
export type ImportEvent = {
  job_id: string
  import_status: ImportStatus
  imported_path: string | null
  import_detail: ImportDetail | null
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
