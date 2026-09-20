export type StreamType = 'hls' | 'dash' | 'http'
export type AudioTrack = { lang: string | null; codec: string; abr: number | null }
export type InspectResult = {
  inspection_id: number
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
}
