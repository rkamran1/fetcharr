import { QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'

import App from '@/App'
import { createQueryClient } from '@/lib/queryClient'

type Handler = (init?: RequestInit) => Response | Promise<Response>

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

export function noContent(): Response {
  return new Response(null, { status: 204 })
}

/** Stubs `fetch` with handlers keyed by "METHOD /path"; anything else gets a 404. */
export function mockApi(routes: Record<string, Handler>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const handler = routes[`${init?.method ?? 'GET'} ${String(input)}`]
    return handler ? handler(init) : json({ detail: 'Not Found' }, 404)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

/** The JSON bodies sent to "METHOD /path". */
export function sentBodies(fetchMock: ReturnType<typeof mockApi>, key: string): unknown[] {
  return fetchMock.mock.calls
    .filter(([input, init]) => `${init?.method ?? 'GET'} ${String(input)}` === key)
    .map(([, init]) => (init?.body ? JSON.parse(String(init.body)) : undefined))
}

/** A stand-in for the browser's EventSource that tests push server events into. */
export class FakeEventSource {
  static last: FakeEventSource | undefined
  readonly url: string
  closed = false
  private listeners = new Map<string, Set<(event: MessageEvent<string>) => void>>()

  constructor(url: string) {
    this.url = url
    FakeEventSource.last = this
  }

  addEventListener(type: string, listener: (event: MessageEvent<string>) => void): void {
    const set = this.listeners.get(type) ?? new Set()
    set.add(listener)
    this.listeners.set(type, set)
  }

  removeEventListener(type: string, listener: (event: MessageEvent<string>) => void): void {
    this.listeners.get(type)?.delete(listener)
  }

  close(): void {
    this.closed = true
  }

  /** Deliver one server-sent event to the page. */
  emit(type: string, data: unknown): void {
    const event = new MessageEvent<string>(type, { data: JSON.stringify(data) })
    for (const listener of this.listeners.get(type) ?? []) listener(event)
  }
}

export function mockEventSource(): typeof FakeEventSource {
  FakeEventSource.last = undefined
  vi.stubGlobal('EventSource', FakeEventSource)
  return FakeEventSource
}

export function renderApp(path: string) {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}
