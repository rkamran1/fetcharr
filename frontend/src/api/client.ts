export type Health = {
  status: string
  version: string
}

export type AuthState = { setup_required: boolean }
export type Me = { username: string }
export type Credentials = { username: string; password: string }
export type PasswordChange = { current_password: string; new_password: string }
export type ApiKey = { api_key: string }

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

export class ApiError extends Error {
  readonly status: number
  /** The parsed JSON error body, when there is one (e.g. `needs_cookies` from inspect). */
  readonly data: unknown

  constructor(status: number, message: string, data?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.data = data
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response.ok) {
    let message = `${method} ${path} failed: ${response.status}`
    let data: unknown
    try {
      data = await response.json()
      const detail = (data as { detail?: unknown })?.detail
      if (typeof detail === 'string') message = detail
      // FastAPI validation errors: a list of {msg}; show the first one.
      else if (Array.isArray(detail) && typeof detail[0]?.msg === 'string')
        message = detail[0].msg.replace(/^Value error, /, '')
    } catch {
      // not a JSON error body; keep the generic message
    }
    throw new ApiError(response.status, message, data)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export async function getHealth(): Promise<Health> {
  const response = await fetch('/healthz')
  if (!response.ok) {
    throw new Error(`GET /healthz failed: ${response.status}`)
  }
  return (await response.json()) as Health
}

export const getAuthState = () => request<AuthState>('GET', '/api/auth/state')
export const setupAccount = (body: Credentials) => request<Me>('POST', '/api/auth/setup', body)
export const login = (body: Credentials) => request<Me>('POST', '/api/auth/login', body)
export const logout = () => request<void>('POST', '/api/auth/logout')
export const getMe = () => request<Me>('GET', '/api/auth/me')
export const changePassword = (body: PasswordChange) =>
  request<void>('POST', '/api/auth/password', body)
export const regenerateApiKey = () => request<ApiKey>('POST', '/api/auth/api-key')
export const inspect = (url: string) => request<InspectResult>('POST', '/api/inspect', { url })
