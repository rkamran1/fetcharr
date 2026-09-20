import type { Numbering } from '@/features/arr'

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

export type DownloadOptions = {
  quality: Quality
  container: Container
  fragments: 'auto' | number
  use_aria2c: 'auto' | boolean
  retries: number
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
  | { media_type: 'other'; items: Item[]; options: DownloadOptions }
  | {
      media_type: 'movie'
      media: MovieMedia
      items: Item[]
      options: DownloadOptions
      collision_policy: CollisionPolicy
    }
  | {
      media_type: 'tv'
      media: TvMedia
      items: EpisodeItem[]
      options: DownloadOptions
      collision_policy: CollisionPolicy
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
