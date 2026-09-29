import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { json, mockApi, noContent, renderApp, sentBodies } from '@/test/mockApi'

const settings = {
  radarr_url: null,
  radarr_api_key_set: false,
  radarr_from_env: false,
  sonarr_url: null,
  sonarr_api_key_set: false,
  sonarr_from_env: false,
  transcode_quality: { 'hevc-qsv': 24, 'hevc-vaapi': 24, 'x265-software': 23 },
  naming_templates: {
    movie_folder: '{Movie Title} ({Release Year})',
    movie_file: '{Movie Title} ({Release Year}) {Quality Full}',
    series_folder: '{Series Title}',
    season_folder: 'Season {season}',
    specials_folder: 'Specials',
    standard_episode: '{Series Title} - S{season:00}E{episode:00} - {Episode Title} {Quality Full}',
    daily_episode: '{Series Title} - {Air-Date} - {Episode Title} {Quality Full}',
    other: '{Title} [{Id}]',
  },
  colon_mode: 'smart',
}

/** What the read-only Paths and yt-dlp sections read (§11). */
const status = {
  version: '1.2.3',
  tools: {
    ytdlp: '2026.09.01',
    ffmpeg: '7.1.1',
    deno: '2.1.4',
    js_runtime: 'deno',
    aria2c: true,
    update_on_start: true,
  },
  paths: {
    ok: true,
    same_filesystem: true,
    checks: [{ path: '/web-downloads/incomplete', ok: true, error: null }],
  },
  transcode: {
    device: false,
    device_path: '/dev/dri/renderD128',
    tested: false,
    hevc_encode: false,
    ok: false,
    message: 'no /dev/dri',
    profiles: [],
  },
  database: { path: '/config/fetcharr.db', size_bytes: 2_000_000, last_backup: null },
  concurrency: { downloads: 2, transcodes: 1 },
  radarr: { configured: false, ok: false, version: null, error: 'not configured' },
  sonarr: { configured: false, ok: false, version: null, error: 'not configured' },
}

const preview = {
  examples: {
    movie: 'movies/Blade Runner - The Final Cut (2007)/…',
    episode: 'tv-shows/Star Trek - Discovery/Season 1/…',
    specials: 'tv-shows/Star Trek - Discovery/Specials/…',
    daily: 'tv-shows/The Daily Show/Season 2026/…',
    other: 'other/A Talk - Part One [dQw4w9WgXcQ].mkv',
  },
  errors: {},
}

const base = {
  'GET /api/auth/me': () => json({ username: 'owner' }),
  'GET /healthz': () => json({ status: 'ok', version: '1.2.3' }),
  'GET /api/settings': () => json(settings),
  'GET /api/system/status': () => json(status),
  'POST /api/settings/naming/preview': () => json(preview),
}

function type(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } })
}

/** The page holds one card per arr app and one for transcoding, so queries are scoped. */
type Region =
  | 'Radarr'
  | 'Sonarr'
  | 'Transcoding'
  | 'Naming'
  | 'Paths and concurrency'
  | 'yt-dlp'
  | 'Change password'

function card(name: Region) {
  return within(screen.getByRole('region', { name }))
}

async function findCard(name: Region) {
  return within(await screen.findByRole('region', { name }))
}

async function fillPasswordForm(current: string) {
  await screen.findByRole('heading', { name: 'Change password' })
  type('Current password', current)
  type('New password', 'a new password')
  type('Repeat new password', 'a new password')
  fireEvent.click(screen.getByRole('button', { name: 'Change password' }))
}

describe('SettingsPage', () => {
  it('changes the password', async () => {
    const fetchMock = mockApi({ ...base, 'POST /api/auth/password': noContent })
    renderApp('/settings')

    await fillPasswordForm('old password')

    expect(await (await findCard('Change password')).findByRole('status')).toHaveTextContent(
      'Password changed.',
    )
    expect(sentBodies(fetchMock, 'POST /api/auth/password')).toEqual([
      { current_password: 'old password', new_password: 'a new password' },
    ])
    expect(screen.getByLabelText('Current password')).toHaveValue('')
  })

  it('shows an error for a wrong current password', async () => {
    mockApi({
      ...base,
      'POST /api/auth/password': () => json({ detail: 'Current password is incorrect' }, 400),
    })
    renderApp('/settings')

    await fillPasswordForm('wrong password')

    expect(await screen.findByRole('alert')).toHaveTextContent('Current password is incorrect')
    expect(card('Change password').queryByRole('status')).not.toBeInTheDocument()
  })

  it('regenerates the API key and shows it once with copy', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    mockApi({ ...base, 'POST /api/auth/api-key': () => json({ api_key: 'k3y-once' }) })
    renderApp('/settings')

    fireEvent.click(await screen.findByRole('button', { name: 'Regenerate API key' }))

    expect(await screen.findByDisplayValue('k3y-once')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Copy' }))
    expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument()
    expect(writeText).toHaveBeenCalledWith('k3y-once')

    fireEvent.click(screen.getByRole('link', { name: 'Home' }))
    await screen.findByRole('heading', { name: 'Home' })
    fireEvent.click(screen.getByRole('link', { name: 'Settings' }))
    await screen.findByRole('heading', { name: 'API key' })
    expect(screen.queryByDisplayValue('k3y-once')).not.toBeInTheDocument()
  })
})

describe('Radarr settings', () => {
  it('saves the connection and never shows the stored key', async () => {
    const fetchMock = mockApi({
      ...base,
      'GET /api/settings': () =>
        json({ ...settings, radarr_url: 'http://radarr:7878', radarr_api_key_set: true }),
      'PATCH /api/settings': () =>
        json({ ...settings, radarr_url: 'http://radarr:7878', radarr_api_key_set: true }),
    })
    renderApp('/settings')

    const radarr = await findCard('Radarr')
    const url = radarr.getByLabelText('Radarr URL')
    await waitFor(() => expect(url).toHaveValue('http://radarr:7878'))
    const apiKey = radarr.getByLabelText('API key')
    expect(apiKey).toHaveValue('')
    expect(apiKey).toHaveAttribute('placeholder', 'Set — type a new key to replace it')

    fireEvent.change(apiKey, { target: { value: 'a-new-key' } })
    fireEvent.click(radarr.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(sentBodies(fetchMock, 'PATCH /api/settings')).toEqual([
        { radarr_url: 'http://radarr:7878', radarr_api_key: 'a-new-key' },
      ]),
    )
  })

  it('tests the connection and reports the version', async () => {
    mockApi({
      ...base,
      'POST /api/arr/radarr/test': () => json({ ok: true, version: '6.4.4', error: null }),
    })
    renderApp('/settings')

    fireEvent.click((await findCard('Radarr')).getByRole('button', { name: 'Test' }))

    expect(await screen.findByText('Connected to Radarr 6.4.4.')).toBeInTheDocument()
  })

  it('reports why the connection did not work', async () => {
    mockApi({
      ...base,
      'POST /api/arr/radarr/test': () =>
        json({ ok: false, version: null, error: 'Radarr rejected the API key; check it in Settings' }),
    })
    renderApp('/settings')

    fireEvent.click((await findCard('Radarr')).getByRole('button', { name: 'Test' }))

    expect(await (await findCard('Radarr')).findByRole('status')).toHaveTextContent(
      "Radarr didn't answer: Radarr rejected the API key; check it in Settings",
    )
  })

  it('locks the fields when the environment sets them', async () => {
    mockApi({
      ...base,
      'GET /api/settings': () =>
        json({
          ...settings,
          radarr_url: 'http://env:7878',
          radarr_api_key_set: true,
          radarr_from_env: true,
        }),
    })
    renderApp('/settings')

    const radarr = await findCard('Radarr')
    await waitFor(() => expect(radarr.getByLabelText('Radarr URL')).toBeDisabled())
    expect(radarr.getByLabelText('API key')).toBeDisabled()
    expect(radarr.getByRole('button', { name: 'Save' })).toBeDisabled()
    expect(radarr.getByText(/RADARR_URL and RADARR_API_KEY are set/)).toBeInTheDocument()
    // The Sonarr card is configured on its own, so nothing there is locked.
    expect(card('Sonarr').getByLabelText('Sonarr URL')).toBeEnabled()
  })
})

describe('Sonarr settings (AC1)', () => {
  it('saves the Sonarr URL and key, and never shows the stored key', async () => {
    const fetchMock = mockApi({
      ...base,
      'PATCH /api/settings': () =>
        json({ ...settings, sonarr_url: 'http://sonarr:8989', sonarr_api_key_set: true }),
    })
    renderApp('/settings')

    const sonarr = await findCard('Sonarr')
    fireEvent.change(sonarr.getByLabelText('Sonarr URL'), {
      target: { value: 'http://sonarr:8989' },
    })
    const apiKey = sonarr.getByLabelText('API key')
    expect(apiKey).toHaveAttribute('placeholder', 'Not set')
    fireEvent.change(apiKey, { target: { value: 'sonarr-key' } })
    fireEvent.click(sonarr.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(sentBodies(fetchMock, 'PATCH /api/settings')).toEqual([
        { sonarr_url: 'http://sonarr:8989', sonarr_api_key: 'sonarr-key' },
      ]),
    )
    // The saved key never comes back, only "set".
    await waitFor(() => expect(sonarr.getByLabelText('API key')).toHaveValue(''))
  })

  it('tests the Sonarr connection and reports the version', async () => {
    mockApi({
      ...base,
      'POST /api/arr/sonarr/test': () => json({ ok: true, version: '4.0.20', error: null }),
    })
    renderApp('/settings')

    fireEvent.click((await findCard('Sonarr')).getByRole('button', { name: 'Test' }))

    expect(await screen.findByText('Connected to Sonarr 4.0.20.')).toBeInTheDocument()
  })

  it('reports why Sonarr did not answer', async () => {
    mockApi({
      ...base,
      'POST /api/arr/sonarr/test': () =>
        json({ ok: false, version: null, error: 'Sonarr rejected the API key' }),
    })
    renderApp('/settings')

    fireEvent.click((await findCard('Sonarr')).getByRole('button', { name: 'Test' }))

    expect(await (await findCard('Sonarr')).findByRole('status')).toHaveTextContent(
      "Sonarr didn't answer: Sonarr rejected the API key",
    )
  })

  it('locks the Sonarr fields when the environment sets them', async () => {
    mockApi({
      ...base,
      'GET /api/settings': () =>
        json({
          ...settings,
          sonarr_url: 'http://env:8989',
          sonarr_api_key_set: true,
          sonarr_from_env: true,
        }),
    })
    renderApp('/settings')

    const sonarr = await findCard('Sonarr')
    await waitFor(() => expect(sonarr.getByLabelText('Sonarr URL')).toBeDisabled())
    expect(sonarr.getByLabelText('API key')).toBeDisabled()
    expect(sonarr.getByRole('button', { name: 'Save' })).toBeDisabled()
    expect(sonarr.getByText(/SONARR_URL and SONARR_API_KEY are set/)).toBeInTheDocument()
  })
})

describe('Transcoding settings', () => {
  const report = {
    device: false,
    device_path: '/dev/dri/renderD128',
    tested: true,
    hevc_encode: false,
    ok: false,
    message: '/dev/dri/renderD128 is not present: pass the iGPU through',
    profiles: [],
  }

  it('shows the stored quality defaults per profile', async () => {
    mockApi(base)
    renderApp('/settings')

    const transcoding = await findCard('Transcoding')
    await waitFor(() =>
      expect(transcoding.getByLabelText('HEVC Intel QSV (global_quality)')).toHaveValue(24),
    )
    expect(transcoding.getByLabelText('HEVC VAAPI (global_quality)')).toHaveValue(24)
    expect(transcoding.getByLabelText('x265 software (CRF)')).toHaveValue(23)
  })

  it('saves the per-profile transcode quality defaults', async () => {
    const saved = {
      ...settings,
      transcode_quality: { 'hevc-qsv': 22, 'hevc-vaapi': 24, 'x265-software': 23 },
    }
    const fetchMock = mockApi({ ...base, 'PATCH /api/settings': () => json(saved) })
    renderApp('/settings')

    const transcoding = await findCard('Transcoding')
    // The stored map has to be in hand first, or saving one profile would drop the others.
    await waitFor(() =>
      expect(transcoding.getByLabelText('x265 software (CRF)')).toHaveValue(23),
    )
    fireEvent.change(transcoding.getByLabelText('HEVC Intel QSV (global_quality)'), {
      target: { value: '22' },
    })
    fireEvent.click(transcoding.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(sentBodies(fetchMock, 'PATCH /api/settings')).toEqual([
        { transcode_quality: { 'hevc-qsv': 22, 'hevc-vaapi': 24, 'x265-software': 23 } },
      ]),
    )
    expect(await transcoding.findByRole('status')).toHaveTextContent('Transcode defaults saved.')
  })

  it('runs the hardware encode test and shows the result', async () => {
    const fetchMock = mockApi({
      ...base,
      'POST /api/system/transcode-test': () => json(report),
    })
    renderApp('/settings')

    const transcoding = await findCard('Transcoding')
    fireEvent.click(transcoding.getByRole('button', { name: 'Test hardware encode' }))

    expect(await transcoding.findByRole('status')).toHaveTextContent(report.message)
    // The encode runs once per click; it is a real one-second encode per profile.
    expect(sentBodies(fetchMock, 'POST /api/system/transcode-test')).toHaveLength(1)
  })

  it('names each profile the hardware test tried', async () => {
    mockApi({
      ...base,
      'POST /api/system/transcode-test': () =>
        json({
          ...report,
          device: true,
          ok: true,
          message: 'hardware encode works with hevc-qsv',
          profiles: [
            { profile: 'hevc-qsv', ok: true, error: null },
            { profile: 'hevc-vaapi', ok: false, error: 'no VAAPI device' },
          ],
        }),
    })
    renderApp('/settings')

    const transcoding = await findCard('Transcoding')
    fireEvent.click(transcoding.getByRole('button', { name: 'Test hardware encode' }))

    expect(await transcoding.findByText('hevc-qsv: works')).toBeInTheDocument()
    expect(transcoding.getByText('hevc-vaapi: no VAAPI device')).toBeInTheDocument()
  })
})

describe('Naming settings (AC3, AC9)', () => {
  it('renders a live example and updates it as the template changes', async () => {
    const fetchMock = mockApi(base)
    renderApp('/settings')
    const naming = await findCard('Naming')

    expect(await naming.findByText(preview.examples.other)).toBeInTheDocument()

    fireEvent.change(naming.getByLabelText('Other file'), { target: { value: '{Id}' } })

    await waitFor(() =>
      expect(sentBodies(fetchMock, 'POST /api/settings/naming/preview').at(-1)).toMatchObject({
        templates: { other: '{Id}' },
      }),
    )
  })

  it('previews the colon mode as well', async () => {
    const fetchMock = mockApi(base)
    renderApp('/settings')
    const naming = await findCard('Naming')

    fireEvent.change(await naming.findByLabelText('Colon replacement'), {
      target: { value: 'delete' },
    })

    await waitFor(() =>
      expect(sentBodies(fetchMock, 'POST /api/settings/naming/preview').at(-1)).toMatchObject({
        colon_mode: 'delete',
      }),
    )
  })

  it("shows the server's reason for a template it cannot use", async () => {
    mockApi({
      ...base,
      'POST /api/settings/naming/preview': () =>
        json({ examples: preview.examples, errors: { other: '{Nope} is not a token' } }),
    })
    renderApp('/settings')
    const naming = await findCard('Naming')

    expect(await naming.findByRole('alert')).toHaveTextContent('{Nope} is not a token')
  })

  it('saves only the templates that were edited', async () => {
    const fetchMock = mockApi(base)
    renderApp('/settings')
    const naming = await findCard('Naming')

    fireEvent.change(naming.getByLabelText('Other file'), { target: { value: '{Id}' } })
    fireEvent.click(naming.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(sentBodies(fetchMock, 'PATCH /api/settings')).toEqual([
        { naming_templates: { other: '{Id}' } },
      ]),
    )
  })

  it('resets the templates to the defaults', async () => {
    const fetchMock = mockApi(base)
    renderApp('/settings')
    const naming = await findCard('Naming')

    fireEvent.click(
      await naming.findByRole('button', { name: 'Reset to Radarr/Sonarr defaults' }),
    )

    await waitFor(() =>
      expect(sentBodies(fetchMock, 'PATCH /api/settings')).toEqual([
        { naming_templates: {}, colon_mode: 'smart' },
      ]),
    )
  })
})

describe('yt-dlp settings (AC1, AC9)', () => {
  it('shows the version and updates it', async () => {
    mockApi({
      ...base,
      'POST /api/settings/yt-dlp/update': () =>
        json({ old: '2026.09.01', new: '2026.09.20', output: 'Successfully installed' }),
    })
    renderApp('/settings')
    const ytdlp = await findCard('yt-dlp')

    expect(await ytdlp.findByText('2026.09.01')).toBeInTheDocument()
    fireEvent.click(ytdlp.getByRole('button', { name: 'Update yt-dlp' }))

    expect(await ytdlp.findByRole('status')).toHaveTextContent(
      'Updated from 2026.09.01 to 2026.09.20',
    )
  })

  it('says so when yt-dlp was already current', async () => {
    mockApi({
      ...base,
      'POST /api/settings/yt-dlp/update': () =>
        json({ old: '2026.09.20', new: '2026.09.20', output: 'Requirement already satisfied' }),
    })
    renderApp('/settings')
    const ytdlp = await findCard('yt-dlp')

    fireEvent.click(await ytdlp.findByRole('button', { name: 'Update yt-dlp' }))

    expect(await ytdlp.findByRole('status')).toHaveTextContent('Already up to date (2026.09.20)')
  })

  it('reports a failed update', async () => {
    mockApi({
      ...base,
      'POST /api/settings/yt-dlp/update': () => json({ detail: 'could not reach the index' }, 502),
    })
    renderApp('/settings')
    const ytdlp = await findCard('yt-dlp')

    fireEvent.click(await ytdlp.findByRole('button', { name: 'Update yt-dlp' }))

    expect(await ytdlp.findByRole('alert')).toHaveTextContent('could not reach the index')
  })
})

describe('Paths and concurrency (AC4, AC9)', () => {
  it('shows the self-test and the concurrency read-only', async () => {
    mockApi(base)
    renderApp('/settings')
    const paths = await findCard('Paths and concurrency')

    expect(await paths.findByRole('status')).toHaveTextContent('Every download folder is writable')
    expect(paths.getByText('/web-downloads/incomplete', { exact: false })).toBeInTheDocument()
    expect(paths.getByText('Concurrent downloads').nextSibling).toHaveTextContent('2')
    expect(paths.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('warns when the folders are on two volumes', async () => {
    mockApi({
      ...base,
      'GET /api/system/status': () =>
        json({ ...status, paths: { ...status.paths, ok: false, same_filesystem: false } }),
    })
    renderApp('/settings')
    const paths = await findCard('Paths and concurrency')

    expect(await paths.findByRole('alert')).toHaveTextContent('different volumes')
  })
})
