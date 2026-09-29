import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { json, mockApi, renderApp } from '@/test/mockApi'

/** The full report the page renders (§11). */
const status = {
  version: '1.2.3',
  tools: {
    ytdlp: '2026.09.20',
    ffmpeg: '7.1.1',
    deno: '2.1.4',
    js_runtime: 'deno',
    aria2c: true,
    update_on_start: true,
  },
  paths: {
    ok: true,
    same_filesystem: true,
    checks: [
      { path: '/web-downloads/incomplete', ok: true, error: null },
      { path: '/web-downloads/completed/movies', ok: true, error: null },
    ],
  },
  transcode: {
    device: true,
    device_path: '/dev/dri/renderD128',
    tested: true,
    hevc_encode: true,
    ok: true,
    message: 'QSV and VAAPI both encode HEVC',
    profiles: [{ profile: 'hevc-qsv', ok: true, error: null }],
  },
  database: {
    path: '/config/fetcharr.db',
    size_bytes: 2_500_000,
    last_backup: 'fetcharr-2026-05-04.db',
  },
  concurrency: { downloads: 2, transcodes: 1 },
  radarr: { configured: true, ok: true, version: '6.4.4', error: null },
  sonarr: { configured: false, ok: false, version: null, error: 'Sonarr is not configured' },
}

const base = {
  'GET /api/auth/me': () => json({ username: 'owner' }),
  'GET /healthz': () => json({ status: 'ok', version: '1.2.3' }),
  'GET /api/system/status': () => json(status),
}

function section(name: string) {
  return within(screen.getByRole('region', { name }))
}

/** The value beside a label, found by the label's own `<dt>`, so a value may repeat. */
function value(region: string, label: string) {
  return section(region).getByText(label, { selector: 'dt' }).nextElementSibling
}

describe('StatusPage (AC4, AC9)', () => {
  it('renders every section of the report', async () => {
    mockApi(base)
    renderApp('/status')

    await screen.findByRole('region', { name: 'Versions' })
    expect(value('Versions', 'fetcharr')).toHaveTextContent('1.2.3')
    expect(value('Versions', 'yt-dlp')).toHaveTextContent('2026.09.20')
    expect(value('Versions', 'ffmpeg')).toHaveTextContent('7.1.1')
    expect(value('Versions', 'deno')).toHaveTextContent('2.1.4')
    expect(value('Versions', 'JS runtime')).toHaveTextContent('deno')
    expect(value('Versions', 'aria2c')).toHaveTextContent('available')
    expect(value('Versions', 'Update yt-dlp on start')).toHaveTextContent('on')

    expect(section('Paths').getByText('/web-downloads/incomplete')).toBeInTheDocument()
    expect(section('Hardware').getByText('/dev/dri/renderD128')).toBeInTheDocument()

    expect(value('Database', 'Size')).toHaveTextContent('2.5 MB')
    expect(value('Database', 'Last backup')).toHaveTextContent('fetcharr-2026-05-04.db')

    expect(value('Library', 'Radarr')).toHaveTextContent('reachable, version 6.4.4')
    expect(value('Library', 'Concurrent downloads')).toHaveTextContent('2')
    expect(value('Library', 'Concurrent transcodes')).toHaveTextContent('1')
  })

  it('shows an unreachable Radarr as an error, with the rest of the report intact', async () => {
    mockApi({
      ...base,
      'GET /api/system/status': () =>
        json({
          ...status,
          radarr: {
            configured: true,
            ok: false,
            version: null,
            error: 'http://radarr:7878 is unreachable: refused',
          },
        }),
    })
    renderApp('/status')

    await screen.findByRole('region', { name: 'Library' })
    expect(value('Library', 'Radarr')).toHaveTextContent(
      'unreachable — http://radarr:7878 is unreachable: refused',
    )
    expect(value('Library', 'Sonarr')).toHaveTextContent('not configured')
    expect(value('Versions', 'fetcharr')).toHaveTextContent('1.2.3')
  })

  it('re-runs the checks on demand', async () => {
    const fetchMock = mockApi(base)
    renderApp('/status')

    fireEvent.click(await screen.findByRole('button', { name: 'Re-run checks' }))

    await waitFor(() =>
      expect(fetchMock.mock.calls.filter(([path]) => path === '/api/system/status')).toHaveLength(2),
    )
  })

  it('names a tool that is not installed', async () => {
    mockApi({
      ...base,
      'GET /api/system/status': () =>
        json({ ...status, tools: { ...status.tools, deno: null, js_runtime: null } }),
    })
    renderApp('/status')

    await screen.findByRole('region', { name: 'Versions' })
    expect(value('Versions', 'deno')).toHaveTextContent('not installed')
    expect(value('Versions', 'JS runtime')).toHaveTextContent('none detected')
  })
})
