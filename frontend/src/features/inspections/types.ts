export type StreamType = 'hls' | 'dash' | 'http'
export type AudioTrack = { lang: string | null; codec: string; abr: number | null }
/** An earlier finished download of the same video: "already downloaded" (§10). */
export type PreviousDownload = {
  job_id: string
  created_at: string
  media_type: 'other' | 'movie' | 'tv'
  /** The library path once imported, else where fetcharr left it in completed/. */
  path: string | null
  import_status: 'n/a' | 'pending' | 'imported' | 'not_imported' | 'error'
}

export type InspectResult = {
  inspection_id: number
  /** The site whose cookies apply to this URL, if any (§8). */
  site_key: string | null
  title: string | null
  uploader: string | null
  thumbnail: string | null
  duration: number | null
  webpage_url: string | null
  extractor: string | null
  id: string | null
  upload_date: string | null
  release_year: number | null
  video_heights: number[]
  video_codecs: string[]
  audio_tracks: AudioTrack[]
  has_hdr: boolean
  subtitles: Record<string, string[]>
  automatic_captions: Record<string, string[]>
  estimated_sizes: Record<string, number>
  stream_type: StreamType
  auto: { fragments: number; use_aria2c: boolean }
  /** Finished downloads of this same video, newest first. */
  previous_downloads?: PreviousDownload[]
}
