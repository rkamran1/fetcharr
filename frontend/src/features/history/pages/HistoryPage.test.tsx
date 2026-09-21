import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { Job } from '@/features/jobs'
import type { RequestPage, RequestRead } from '@/features/requests'
import type { Site } from '@/features/sites'
import { json, renderApp } from '@/test/mockApi'

type Handler = (init?: RequestInit) => Response | Promise<Response>

const base: Record<string, Handler> = {
  'GET /api/auth/me': () => json({ username: 'owner' }),
  'GET /healthz': () => json({ status: 'ok', version: '1.2.3' }),
}

const SITES: Site[] = [
  {
    key: 'youtube',
    label: 'YouTube',
    domains: ['youtube.com'],
    builtin: true,
    status: 'none',
    cookie_count: null,
    earliest_expiry: null,
    last_used_at: null,
    uploaded_at: null,
  },
]

const OPTIONS = {
  quality: '720p',
  container: 'mp4',
  fragments: 'auto',
  use_aria2c: 'auto',
  retries: 5,
  transcode: 'off',
  transcode_quality: null,
} as const

function job(id: string, overrides: Partial<Job> = {}): Job {
  return {
    id,
    request_id: `req-${id}`,
    media_type: 'movie',
    request_title: 'Big Buck Bunny',
    url: `https://www.youtube.com/watch?v=${id}`,
    source_title: 'Big Buck Bunny 4K',
    thumbnail_url: null,
    duration: 635,
    status: 'completed',
    phase: null,
    attempt: 1,
    progress_pct: 100,
    downloaded_bytes: null,
    total_bytes: null,
    speed_bps: null,
    eta_s: null,
    completed_path: `/web-downloads/completed/movies/${id}.mkv`,
    file_size: 1000,
    transcode_fallback_used: false,
    site_key: 'youtube',
    file_deleted_at: null,
    season: null,
    episode: null,
    episode_title: null,
    air_date: null,
    sonarr_episode_id: null,
    import_status: 'n/a',
    import_attempts: 0,
    import_detail: null,
    imported_path: null,
    imported_at: null,
    error_code: null,
    error_message: null,
    created_at: '2026-09-20T10:00:00',
    started_at: '2026-09-20T10:00:01',
    finished_at: '2026-09-20T10:05:00',
    ...overrides,
  }
}

function request(
  media_type: RequestRead['media_type'],
  jobs: Job[],
  overrides: Partial<RequestRead> = {},
): RequestRead {
  return {
    id: jobs[0].request_id,
    media_type,
    title: 'Big Buck Bunny',
    year: media_type === 'movie' ? 2008 : null,
    numbering: media_type === 'tv' ? 'standard' : null,
    radarr_movie_id: media_type === 'movie' ? 7 : null,
    sonarr_series_id: media_type === 'tv' ? 3 : null,
    options: OPTIONS,
    created_at: '2026-09-20T10:00:00',
    jobs,
    ...overrides,
  }
}

const IMPORTED = request('movie', [
  job('imported', {
    import_status: 'imported',
    imported_path: '/movies/Big Buck Bunny (2008)/Big Buck Bunny (2008) WEBDL-1080p.mkv',
  }),
])
const REJECTED = request(
  'movie',
  [
    job('rejected', {
      import_status: 'not_imported',
      import_detail: { rejections: ['Not an upgrade for existing movie file'] },
    }),
  ],
  { title: 'Sintel' },
)
const FAILED = request(
  'other',
  [
    job('failed', {
      media_type: 'other',
      status: 'failed',
      completed_path: null,
      error_message: 'HTTP Error 403: Forbidden',
    }),
  ],
  { title: 'A clip' },
)
const EPISODE = request(
  'tv',
  [
    job('episode', {
      media_type: 'tv',
      season: 1,
      episode: 2,
      episode_title: 'Second',
      sonarr_episode_id: 102,
      import_status: 'imported',
      imported_path: '/tv/Some Show/Season 1/Some Show - S01E02.mkv',
    }),
  ],
  { title: 'Some Show' },
)

function page(items: RequestRead[] = [IMPORTED, REJECTED, FAILED, EPISODE]): RequestPage {
  return { items, total: items.length, page: 1, per_page: 25 }
}

function screenIs(desktop: boolean) {
  vi.stubGlobal('matchMedia', (media: string) => ({
    matches: desktop,
    media,
    addEventListener: () => {},
    removeEventListener: () => {},
  }))
}

/** `fetch`, with every `GET /api/requests?…` answered by `list` and its query recorded. */
function mockHistory(list: () => RequestPage = () => page(), routes: Record<string, Handler> = {}) {
  const queries: URLSearchParams[] = []
  const all: Record<string, Handler> = {
    ...base,
    'GET /api/sites': () => json(SITES),
    ...routes,
  }
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    if (method === 'GET' && /^\/api\/requests(\?|$)/.test(url)) {
      queries.push(new URLSearchParams(url.split('?')[1] ?? ''))
      return json(list())
    }
    const handler = all[`${method} ${url}`]
    return handler ? handler(init) : json({ detail: 'Not Found' }, 404)
  })
  vi.stubGlobal('fetch', fetchMock)
  return { fetchMock, queries }
}

function calls(fetchMock: ReturnType<typeof vi.fn>, key: string): number {
  return fetchMock.mock.calls.filter(
    ([input, init]) =>
      `${(init as RequestInit | undefined)?.method ?? 'GET'} ${String(input)}` === key,
  ).length
}

/** The table row, or the mobile card, holding this text. */
async function rowOf(text: string): Promise<HTMLElement> {
  const cell = await screen.findByText(text)
  return (cell.closest('tr') ?? cell.closest('li'))!
}

describe('HistoryPage', () => {
  it('sends each filter as a query parameter', async () => {
    screenIs(true)
    const { queries } = mockHistory()
    renderApp('/history')
    await screen.findByText('Sintel')
    expect(Object.fromEntries(queries.at(-1)!)).toEqual({
      page: '1',
      per_page: '25',
    })

    fireEvent.change(screen.getByLabelText('Type'), {
      target: { value: 'movie' },
    })
    fireEvent.change(screen.getByLabelText('Status'), {
      target: { value: 'completed' },
    })
    fireEvent.change(screen.getByLabelText('Import'), {
      target: { value: 'not_imported' },
    })
    // The site options come from GET /api/sites.
    await screen.findByRole('option', { name: 'YouTube' })
    fireEvent.change(screen.getByLabelText('Site'), { target: { value: 'youtube' } })
    fireEvent.change(screen.getByLabelText('From'), {
      target: { value: '2026-09-01' },
    })
    fireEvent.change(screen.getByLabelText('To'), {
      target: { value: '2026-09-30' },
    })

    await waitFor(() =>
      expect(Object.fromEntries(queries.at(-1)!)).toEqual({
        type: 'movie',
        status: 'completed',
        import_status: 'not_imported',
        site: 'youtube',
        from: '2026-09-01',
        to: '2026-09-30',
        page: '1',
        per_page: '25',
      }),
    )

    // Back to "Any" drops the filter again.
    fireEvent.change(screen.getByLabelText('Type'), { target: { value: '' } })
    await waitFor(() => expect(queries.at(-1)!.has('type')).toBe(false))
  })

  it('debounces the search box into one request', async () => {
    screenIs(true)
    const { queries } = mockHistory()
    renderApp('/history')
    await screen.findByText('Sintel')

    const box = screen.getByRole('searchbox', { name: 'Search history' })
    for (const typed of ['b', 'bu', 'bun']) fireEvent.change(box, { target: { value: typed } })

    await waitFor(() => expect(queries.at(-1)!.get('q')).toBe('bun'))
    expect(queries.map((query) => query.get('q')).filter(Boolean)).toEqual(['bun'])
  })

  it('renders a table on desktop and cards on mobile', async () => {
    screenIs(true)
    mockHistory()
    const desktop = renderApp('/history')
    const table = await screen.findByRole('table')
    expect(within(table).getAllByRole('row')).toHaveLength(5)
    expect(within(table).getByText('Some Show · S01E02 · Second')).toBeInTheDocument()
    desktop.unmount()

    screenIs(false)
    mockHistory()
    renderApp('/history')
    const cards = await screen.findByRole('list', { name: 'History' })
    // One card per job; the reasons inside a card are a list of their own.
    expect([...cards.children].filter((child) => child.tagName === 'LI')).toHaveLength(4)
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('disables delete for an imported job and says why', async () => {
    screenIs(false)
    mockHistory()
    renderApp('/history')

    const imported = await rowOf(
      '/movies/Big Buck Bunny (2008)/Big Buck Bunny (2008) WEBDL-1080p.mkv',
    )
    const button = within(imported).getByRole('button', {
      name: 'Delete file',
    })
    expect(button).toBeDisabled()
    expect(button).toHaveAccessibleDescription('Managed by Radarr/Sonarr now')
    expect(button.parentElement).toHaveAttribute('title', 'Managed by Radarr/Sonarr now')

    const rejected = await rowOf('Sintel')
    expect(within(rejected).getByRole('button', { name: 'Delete file' })).toBeEnabled()
    // No file to delete for a download that never finished.
    expect(
      within(await rowOf('A clip')).queryByRole('button', {
        name: 'Delete file',
      }),
    ).toBeNull()
  })

  it('deletes a file after confirming and refreshes', async () => {
    screenIs(true)
    let current = page()
    const deleted = {
      ...REJECTED.jobs[0],
      file_deleted_at: '2026-09-21T10:00:00',
    }
    const { fetchMock, queries } = mockHistory(() => current, {
      'DELETE /api/jobs/rejected/file': () => {
        current = page([IMPORTED, { ...REJECTED, jobs: [deleted] }, FAILED, EPISODE])
        return json(deleted)
      },
    })
    const confirm = vi.fn(() => false)
    vi.stubGlobal('confirm', confirm)
    renderApp('/history')
    const row = await rowOf('Sintel')

    fireEvent.click(within(row).getByRole('button', { name: 'Delete file' }))
    expect(confirm).toHaveBeenCalledOnce()
    expect(calls(fetchMock, 'DELETE /api/jobs/rejected/file')).toBe(0)

    confirm.mockReturnValue(true)
    const before = queries.length
    fireEvent.click(within(row).getByRole('button', { name: 'Delete file' }))

    expect(await within(await rowOf('Sintel')).findByText('File deleted')).toBeInTheDocument()
    expect(calls(fetchMock, 'DELETE /api/jobs/rejected/file')).toBe(1)
    expect(queries.length).toBeGreaterThan(before)
    expect(
      within(await rowOf('Sintel')).queryByRole('button', {
        name: 'Delete file',
      }),
    ).toBeNull()
  })

  it('retries a download and an import, and opens the log', async () => {
    screenIs(true)
    const { fetchMock } = mockHistory(undefined, {
      'POST /api/jobs/failed/retry': () => json({ ...FAILED.jobs[0], status: 'queued' }),
      'POST /api/jobs/rejected/import': () =>
        json({ ...REJECTED.jobs[0], import_status: 'pending' }),
      'GET /api/jobs/failed/log': () =>
        json({
          lines: [{ ts: '2026-09-20T10:00:02', level: 'error', line: 'ERROR: 403' }],
        }),
    })
    renderApp('/history')

    const failed = await rowOf('A clip')
    expect(within(failed).getByText('HTTP Error 403: Forbidden')).toBeInTheDocument()
    fireEvent.click(within(failed).getByRole('button', { name: 'Retry download' }))
    await waitFor(() => expect(calls(fetchMock, 'POST /api/jobs/failed/retry')).toBe(1))

    fireEvent.click(
      within(await rowOf('Sintel')).getByRole('button', {
        name: 'Retry import',
      }),
    )
    await waitFor(() => expect(calls(fetchMock, 'POST /api/jobs/rejected/import')).toBe(1))

    fireEvent.click(within(await rowOf('A clip')).getByRole('button', { name: 'Open log' }))
    const log = await screen.findByRole('region', { name: 'Log' })
    await waitFor(() => expect(log).toHaveTextContent('ERROR: 403'))
    fireEvent.click(within(await rowOf('A clip')).getByRole('button', { name: 'Hide log' }))
    expect(screen.queryByRole('region', { name: 'Log' })).not.toBeInTheDocument()
  })

  it('shows the library path when imported and the reasons when not', async () => {
    screenIs(true)
    mockHistory()
    renderApp('/history')

    const imported = await rowOf(
      '/movies/Big Buck Bunny (2008)/Big Buck Bunny (2008) WEBDL-1080p.mkv',
    )
    expect(within(imported).getByText('✅ Imported')).toBeInTheDocument()

    const rejected = await rowOf('Sintel')
    expect(within(rejected).getByText('⚠ Not imported')).toBeInTheDocument()
    expect(
      within(within(rejected).getByRole('list', { name: "Radarr's reasons" })).getByText(
        'Not an upgrade for existing movie file',
      ),
    ).toBeInTheDocument()
  })

  it.each([
    ['Sintel', 'Download Movie'],
    ['A clip', 'Download Other'],
  ])('download again on %s opens %s', async (row, heading) => {
    screenIs(true)
    mockHistory(undefined, {
      'GET /api/requests/req-rejected': () => json(REJECTED),
      'GET /api/requests/req-failed': () => json(FAILED),
    })
    renderApp('/history')

    fireEvent.click(within(await rowOf(row)).getByRole('button', { name: 'Download again' }))

    expect(await screen.findByRole('heading', { name: heading })).toBeInTheDocument()
  })

  it('download again on an episode opens its series', async () => {
    screenIs(true)
    mockHistory(undefined, {
      'GET /api/requests/req-episode': () => json(EPISODE),
      'GET /api/arr/sonarr/series?q=': () =>
        json({
          series: [
            {
              id: 3,
              title: 'Some Show',
              series_type: 'standard',
              monitored: true,
              seasons: [],
              poster: null,
            },
          ],
        }),
    })
    renderApp('/history')

    fireEvent.click(
      within(await rowOf('Some Show · S01E02 · Second')).getByRole('button', {
        name: 'Download again',
      }),
    )

    expect(await screen.findByRole('heading', { name: 'Some Show' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '← All missing series' })).toBeInTheDocument()
  })
})
