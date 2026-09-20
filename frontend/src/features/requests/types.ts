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

export type CreateRequest = {
  media_type: 'other'
  items: { inspection_id: number }[]
  options: DownloadOptions
}

export type CreatedRequest = { id: string; jobs: string[] }

export type PreviewRequest = {
  media_type: 'other'
  inspection_id: number
  options: DownloadOptions
}

export type PathPreview = { path: string }
