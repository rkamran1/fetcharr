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

export type SystemStatus = { version: string; paths: PathReport; transcode: TranscodeReport }
