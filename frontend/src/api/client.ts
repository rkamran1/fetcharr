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

/** The one place a request is sent; every feature's `api.ts` goes through it. */
export async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
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
