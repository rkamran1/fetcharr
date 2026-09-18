export type Health = {
  status: string
  version: string
}

export type AuthState = { setup_required: boolean }
export type Me = { username: string }
export type Credentials = { username: string; password: string }
export type PasswordChange = { current_password: string; new_password: string }
export type ApiKey = { api_key: string }

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
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
    try {
      const data = await response.json()
      if (typeof data?.detail === 'string') message = data.detail
    } catch {
      // not a JSON error body; keep the generic message
    }
    throw new ApiError(response.status, message)
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
