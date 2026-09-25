import type { Numbering } from '@/features/arr'
import type { ImportStatus, Job, JobStatus } from '@/features/jobs'

export type Quality =
  | '144p'
  | '240p'
  | '360p'
  | '480p'
  | '720p'
  | '1080p'
  | '1440p'
  | '2160p'
  | 'best'
export type Container = 'mkv' | 'mp4'

/** What a download is re-encoded with; `off` (the default) only remuxes (§5 step 2d). */
export type TranscodeProfile = 'off' | 'hevc-qsv' | 'hevc-vaapi' | 'x265-software'

export type SubtitleMode = 'off' | 'embed' | 'sidecar'
export type SponsorBlockMode = 'off' | 'mark' | 'remove'
export type VideoCodec = 'any' | 'h264' | 'vp9' | 'av1'

/** `sidecar` writes `<video base>.<lang>.srt` next to the file, which arr imports too. */
export type SubtitleOptions = {
  mode: SubtitleMode
  languages: string[]
  include_auto_captions: boolean
}

/** Empty `categories` means the mode's own default: `all` to mark, the ad types to remove. */
export type SponsorBlockOptions = {
  mode: SponsorBlockMode
  categories: string[]
}

export type DownloadOptions = {
  quality: Quality
  container: Container
  fragments: 'auto' | number
  use_aria2c: 'auto' | boolean
  retries: number
  /** Off unless the user picks a profile: nothing transcodes by itself. */
  transcode: TranscodeProfile
  /** `null` means "use the default stored in Settings for this profile" (§4.1). */
  transcode_quality: number | null
  subtitles: SubtitleOptions
  sponsorblock: SponsorBlockOptions
  /** A language from the inspection's `audio_tracks`; `null` is yt-dlp's best track. */
  audio_language: string | null
  video_codec: VideoCodec
  allow_hdr: boolean
  /** yt-dlp's `--limit-rate`, e.g. `500K` or `1.5M`; `null` is unlimited. */
  rate_limit: string | null
  embed_metadata: boolean
  embed_chapters: boolean
}

/** What every wizard starts from, so transcoding is off wherever a download begins. */
export const DEFAULT_OPTIONS: DownloadOptions = {
  quality: 'best',
  container: 'mkv',
  fragments: 'auto',
  use_aria2c: 'auto',
  retries: 5,
  transcode: 'off',
  transcode_quality: null,
  subtitles: { mode: 'off', languages: [], include_auto_captions: false },
  sponsorblock: { mode: 'off', categories: [] },
  audio_language: null,
  video_codec: 'any',
  allow_hdr: true,
  rate_limit: null,
  embed_metadata: true,
  embed_chapters: true,
}

/** Step 2a: what Radarr calls this movie, and which movie it is when one was picked. */
export type MovieMedia = {
  radarr_movie_id: number | null
  title: string
  year: number | null
}

/** Step 2b: what Sonarr calls this series, and how it numbers its episodes. */
export type TvMedia = {
  sonarr_series_id: number | null
  title: string
  numbering: Numbering
}

/** Which episode one video is, as picked from Sonarr (§5 step 2b, §10). */
export type EpisodeRef = {
  season: number | null
  number?: number | null
  sonarr_episode_id?: number | null
  title?: string
  /** `YYYY-MM-DD`; a daily series is numbered by this instead of by `number`. */
  air_date?: string | null
}

/** What to do when an un-imported file is already sitting at the destination (§7.3). */
export type CollisionPolicy = 'ask' | 'replace' | 'keep_both'

type Item = { inspection_id: number }
type EpisodeItem = Item & { episode: EpisodeRef }

export type CreateRequest =
  | { media_type: 'other'; items: Item[]; options: DownloadOptions; use_cookies: boolean }
  | {
      media_type: 'movie'
      media: MovieMedia
      items: Item[]
      options: DownloadOptions
      collision_policy: CollisionPolicy
      use_cookies: boolean
    }
  | {
      media_type: 'tv'
      media: TvMedia
      items: EpisodeItem[]
      options: DownloadOptions
      collision_policy: CollisionPolicy
      use_cookies: boolean
    }

export type CreatedRequest = { id: string; jobs: string[] }

export type PreviewRequest =
  | { media_type: 'other'; inspection_id: number; options: DownloadOptions }
  | {
      media_type: 'movie'
      media: MovieMedia
      inspection_id: number
      options: DownloadOptions
    }
  | {
      media_type: 'tv'
      media: TvMedia
      inspection_id: number
      episode: EpisodeRef
      options: DownloadOptions
    }

export type PathPreview = { path: string; exists: boolean }

export type MediaType = 'other' | 'movie' | 'tv'

/** A request with what "download again" needs to prefill its wizard (§12). */
export type RequestRead = {
  id: string
  media_type: MediaType
  title: string | null
  year: number | null
  numbering: Numbering | null
  radarr_movie_id: number | null
  sonarr_series_id: number | null
  /** As stored; a request older than a field has no value for it. */
  options: Partial<DownloadOptions>
  created_at: string
  jobs: Job[]
}

/** History's filters and page (§11); an unset filter is left out of the query. */
export type RequestFilters = {
  type?: MediaType
  status?: JobStatus
  import_status?: ImportStatus
  site?: string
  /** `YYYY-MM-DD`, inclusive, UTC. */
  from?: string
  to?: string
  q?: string
  page?: number
  per_page?: number
}

export type RequestPage = {
  items: RequestRead[]
  total: number
  page: number
  per_page: number
}
