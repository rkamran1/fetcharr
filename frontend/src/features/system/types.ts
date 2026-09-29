export type Health = {
  status: string
  version: string
}

export type PathCheck = { path: string; ok: boolean; error: string | null }

export type PathReport = { ok: boolean; same_filesystem: boolean; checks: PathCheck[] }

/** One hardware profile's one-second test encode (§13.1). */
export type ProfileCheck = { profile: string; ok: boolean; error: string | null }

/** The `/dev/dri` + QSV/VAAPI check behind Settings' hardware test (§11). */
export type TranscodeReport = {
  device: boolean
  device_path: string
  /** False until the full test has run; startup only looks at the render device. */
  tested: boolean
  hevc_encode: boolean
  ok: boolean
  message: string
  profiles: ProfileCheck[]
}

/** The binaries the downloads lean on; null means the tool isn't installed. */
export type Tools = {
  ytdlp: string | null
  ffmpeg: string | null
  deno: string | null
  js_runtime: string | null
  aria2c: boolean
  /** Whether the container upgrades yt-dlp before it starts (§13.1). */
  update_on_start: boolean
}

export type DatabaseStatus = { path: string; size_bytes: number | null; last_backup: string | null }

/** Sized from the environment at startup, so Settings and Status show them read-only. */
export type Concurrency = { downloads: number; transcodes: number }

export type ArrStatus = {
  configured: boolean
  ok: boolean
  version: string | null
  error: string | null
}

/** The full status report (§11), everything the Status page shows. */
export type SystemStatus = {
  version: string
  tools: Tools
  paths: PathReport
  transcode: TranscodeReport
  database: DatabaseStatus
  concurrency: Concurrency
  radarr: ArrStatus
  sonarr: ArrStatus
}
