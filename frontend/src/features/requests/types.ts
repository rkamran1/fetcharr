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

/** What to do when an un-imported file is already sitting at the destination (§7.3). */
export type CollisionPolicy = 'ask' | 'replace' | 'keep_both'

type Item = { inspection_id: number }

export type CreateRequest =
  | { media_type: 'other'; items: Item[]; options: DownloadOptions }
  | {
      media_type: 'movie'
      media: MovieMedia
      items: Item[]
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

export type PathPreview = { path: string; exists: boolean }
