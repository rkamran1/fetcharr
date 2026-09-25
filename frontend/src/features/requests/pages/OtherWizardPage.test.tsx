import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { InspectResult } from '@/features/inspections'
import type { Job } from '@/features/jobs'
import type { Preset } from '@/features/presets'
import type { Site } from '@/features/sites'
import { json, mockApi, mockEventSource, renderApp, sentBodies } from '@/test/mockApi'

import { DEFAULT_OPTIONS } from '../types'
import type { DownloadOptions, RequestRead } from '../types'

const base = {
  'GET /api/auth/me': () => json({ username: 'owner' }),
  'GET /healthz': () => json({ status: 'ok', version: '1.2.3' }),
}

const URL = 'https://www.youtube.com/watch?v=aqz-KE-bpKQ'

const result: InspectResult = {
  inspection_id: 7,
  site_key: 'youtube',
  title: 'Big Buck Bunny',
  uploader: 'Blender',
  thumbnail: 'https://i.ytimg.com/vi/aqz-KE-bpKQ/maxresdefault.jpg',
  duration: 635,
  webpage_url: URL,
  extractor: 'youtube',
  id: 'aqz-KE-bpKQ',
  upload_date: '20141110',
  release_year: 2014,
  video_heights: [2160, 1080, 720],
  video_codecs: ['av01', 'avc1', 'vp9'],
  audio_tracks: [{ lang: null, codec: 'opus', abr: 129 }],
  has_hdr: false,
  subtitles: {},
  automatic_captions: {},
  estimated_sizes: { '2160': 1372540977 },
  stream_type: 'dash',
  auto: { fragments: 4, use_aria2c: false },
}

/** An ISO timestamp `days` from now, naive UTC like the backend's. */
function inDays(days: number): string {
  return new Date(Date.now() + days * 86_400_000 - 60_000).toISOString().slice(0, 19)
}

function site(overrides: Partial<Site> = {}): Site {
  return {
    key: 'youtube',
    label: 'YouTube',
    domains: ['youtube.com'],
    builtin: true,
    status: 'valid',
    cookie_count: 12,
    earliest_expiry: inDays(200),
    last_used_at: null,
    uploaded_at: '2026-09-01T10:00:00',
    ...overrides,
  }
}

const preview = { path: '/web-downloads/completed/other/Big Buck Bunny [aqz-KE-bpKQ].mkv' }

async function inspectUrl(url = URL) {
  fireEvent.change(await screen.findByLabelText('Video URL'), { target: { value: url } })
  fireEvent.click(screen.getByRole('button', { name: 'Inspect' }))
}

describe('Other wizard', () => {
  it('shows a loading state while inspecting', async () => {
    mockApi({ ...base, 'POST /api/inspect': () => new Promise<Response>(() => {}) })
    renderApp('/download/other')

    await inspectUrl()

    expect(await screen.findByRole('status')).toHaveTextContent('Inspecting…')
    expect(screen.getByRole('button', { name: 'Inspect' })).toBeDisabled()
  })

  it('shows the inspected video', async () => {
    const fetchMock = mockApi({
      ...base,
      'POST /api/inspect': () => json(result),
      'POST /api/preview': () => json(preview),
    })
    renderApp('/download/other')

    await inspectUrl(`  ${URL}  `)

    expect(await screen.findByRole('heading', { name: 'Big Buck Bunny' })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Big Buck Bunny' })).toHaveAttribute(
      'src',
      result.thumbnail,
    )
    expect(screen.getByText('Blender · 10:35')).toBeInTheDocument()
    const chips = within(screen.getByRole('list', { name: 'Qualities' })).getAllByRole('listitem')
    expect(chips.map((chip) => chip.textContent)).toEqual(['2160p', '1080p', '720p'])
    expect(screen.getByText('DASH')).toBeInTheDocument()
    expect(sentBodies(fetchMock, 'POST /api/inspect')).toEqual([{ url: URL }])
  })

  it('shows the error message', async () => {
    mockApi({
      ...base,
      'POST /api/inspect': () =>
        json(
          { detail: "Playlists aren't supported, paste a single video URL.", needs_cookies: false },
          422,
        ),
    })
    renderApp('/download/other')

    await inspectUrl()

    expect(await screen.findByRole('alert')).toHaveTextContent(
      "Playlists aren't supported, paste a single video URL.",
    )
    expect(screen.queryByText('This video needs cookies.')).not.toBeInTheDocument()
  })

  it('shows the needs-cookies state', async () => {
    mockApi({
      ...base,
      'POST /api/inspect': () =>
        json({ detail: 'Sign in to confirm your age.', needs_cookies: true }, 422),
    })
    renderApp('/download/other')

    await inspectUrl()

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('This video needs cookies.')
    expect(alert).toHaveTextContent('Sign in to confirm your age.')
  })

  it('links the needs-cookies state to the Cookies page', async () => {
    mockApi({
      ...base,
      'POST /api/inspect': () =>
        json(
          { detail: 'Sign in to confirm your age.', needs_cookies: true, site_key: 'youtube' },
          422,
        ),
    })
    renderApp('/download/other')

    await inspectUrl()

    const link = await screen.findByRole('link', { name: 'Add cookies for youtube' })
    expect(link).toHaveAttribute('href', '/cookies#youtube')
  })

  it('shows the cookies chip and sends use_cookies', async () => {
    const fetchMock = mockApi({
      ...base,
      'POST /api/inspect': () => json(result),
      'POST /api/preview': () => json(preview),
      'GET /api/sites': () => json([site({ earliest_expiry: inDays(12) })]),
      'POST /api/requests': () => json({ id: 'r1', jobs: ['j1'] }, 201),
      'GET /api/jobs': () => json({ jobs: [] }),
    })
    mockEventSource()
    renderApp('/download/other')

    await inspectUrl()

    const chip = await screen.findByRole('group', { name: 'Cookies' })
    expect(chip).toHaveTextContent('Using youtube cookies (expires in 12 days)')
    expect(within(chip).getByRole('checkbox', { name: 'Skip cookies' })).not.toBeChecked()
    fireEvent.click(screen.getByRole('button', { name: 'Download' }))

    await screen.findByRole('heading', { name: 'Queue' })
    expect(sentBodies(fetchMock, 'POST /api/requests')).toMatchObject([{ use_cookies: true }])
  })

  it('skip cookies sends use_cookies false', async () => {
    const fetchMock = mockApi({
      ...base,
      'POST /api/inspect': () => json(result),
      'POST /api/preview': () => json(preview),
      'GET /api/sites': () => json([site({ status: 'flagged' })]),
      'POST /api/requests': () => json({ id: 'r1', jobs: ['j1'] }, 201),
      'GET /api/jobs': () => json({ jobs: [] }),
    })
    mockEventSource()
    renderApp('/download/other')

    await inspectUrl()

    const chip = await screen.findByRole('group', { name: 'Cookies' })
    expect(within(chip).getByRole('link', { name: 'Check Cookies' })).toHaveAttribute(
      'href',
      '/cookies#youtube',
    )
    fireEvent.click(within(chip).getByRole('checkbox', { name: 'Skip cookies' }))
    fireEvent.click(screen.getByRole('button', { name: 'Download' }))

    await screen.findByRole('heading', { name: 'Queue' })
    expect(sentBodies(fetchMock, 'POST /api/requests')).toMatchObject([{ use_cookies: false }])
  })

  it('shows no chip when the site has no cookies', async () => {
    mockApi({
      ...base,
      'POST /api/inspect': () => json(result),
      'POST /api/preview': () => json(preview),
      'GET /api/sites': () => json([site({ status: 'none', cookie_count: null })]),
    })
    renderApp('/download/other')

    await inspectUrl()

    expect(await screen.findByText(preview.path)).toBeInTheDocument()
    expect(screen.queryByRole('group', { name: 'Cookies' })).not.toBeInTheDocument()
  })

  it('previews the path and posts the chosen options', async () => {
    const fetchMock = mockApi({
      ...base,
      'POST /api/inspect': () => json(result),
      'POST /api/preview': () => json(preview),
      'POST /api/requests': () => json({ id: 'r1', jobs: ['j1'] }, 201),
      'GET /api/jobs': () => json({ jobs: [] }),
    })
    mockEventSource()
    renderApp('/download/other')

    await inspectUrl()
    fireEvent.change(await screen.findByLabelText('Quality'), { target: { value: '1080p' } })
    expect(await screen.findByText(preview.path)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Download' }))

    expect(await screen.findByRole('heading', { name: 'Queue' })).toBeInTheDocument()
    expect(sentBodies(fetchMock, 'POST /api/requests')).toEqual([
      {
        media_type: 'other',
        items: [{ inspection_id: 7 }],
        options: {
          quality: '1080p',
          container: 'mkv',
          fragments: 'auto',
          use_aria2c: 'auto',
          retries: 5,
          transcode: 'off',
          transcode_quality: null,
          subtitles: { mode: 'off', languages: [], include_auto_captions: false },
          sponsorblock: { mode: 'off', categories: [] },
          audio_language: null,
          video_codec: 'any',
          allow_hdr: true,
          rate_limit: null,
          embed_metadata: true,
          embed_chapters: true,
        },
        use_cookies: true,
      },
    ])
    expect(sentBodies(fetchMock, 'POST /api/preview')).toContainEqual({
      media_type: 'other',
      inspection_id: 7,
      options: {
        quality: '1080p',
        container: 'mkv',
        fragments: 'auto',
        use_aria2c: 'auto',
        retries: 5,
        transcode: 'off',
        transcode_quality: null,
        subtitles: { mode: 'off', languages: [], include_auto_captions: false },
        sponsorblock: { mode: 'off', categories: [] },
        audio_language: null,
        video_codec: 'any',
        allow_hdr: true,
        rate_limit: null,
        embed_metadata: true,
        embed_chapters: true,
      },
    })
  })

  it('offers every inspected height, highest first, and names what best means', async () => {
    mockApi({
      ...base,
      'POST /api/inspect': () =>
        json({ ...result, video_heights: [2160, 1440, 1080, 720, 480, 360, 240, 144] }),
      'POST /api/preview': () => json(preview),
    })
    renderApp('/download/other')

    await inspectUrl()

    const select = (await screen.findByLabelText('Quality')) as HTMLSelectElement
    expect([...select.options].map((option) => option.value)).toEqual([
      'best',
      '2160p',
      '1440p',
      '1080p',
      '720p',
      '480p',
      '360p',
      '240p',
      '144p',
    ])
    expect(select.options[0].textContent).toBe('Best available (2160p · ≈ 1.3 GB)')
  })

  it('shows the estimated size of each quality it knows one for', async () => {
    mockApi({
      ...base,
      'POST /api/inspect': () =>
        json({
          ...result,
          video_heights: [1080, 720, 360],
          // yt-dlp knows a size for some heights and not others (§5 step 1).
          estimated_sizes: { '1080': 250_000_000, '720': 94_371_840 },
        }),
      'POST /api/preview': () => json(preview),
    })
    renderApp('/download/other')

    await inspectUrl()

    const select = (await screen.findByLabelText('Quality')) as HTMLSelectElement
    expect([...select.options].map((option) => option.textContent)).toEqual([
      'Best available (1080p · ≈ 238 MB)',
      '1080p · ≈ 238 MB',
      '720p · ≈ 90 MB',
      '360p',
    ])
    // The value posted is still the plain quality, not the label.
    expect([...select.options].map((option) => option.value)).toEqual([
      'best',
      '1080p',
      '720p',
      '360p',
    ])
  })

  it('offers only the heights the video really has', async () => {
    mockApi({
      ...base,
      'POST /api/inspect': () => json({ ...result, video_heights: [720, 360] }),
      'POST /api/preview': () => json(preview),
    })
    renderApp('/download/other')

    await inspectUrl()

    const select = (await screen.findByLabelText('Quality')) as HTMLSelectElement
    expect([...select.options].map((option) => option.value)).toEqual(['best', '720p', '360p'])
    expect(select.options[0].textContent).toBe('Best available (720p)')
  })

  it('copes with heights that are strings', async () => {
    mockApi({
      ...base,
      'POST /api/inspect': () =>
        json({ ...result, video_heights: ['1080', '720', '360'] }),
      'POST /api/preview': () => json(preview),
    })
    renderApp('/download/other')

    await inspectUrl()

    const select = (await screen.findByLabelText('Quality')) as HTMLSelectElement
    expect([...select.options].map((option) => option.value)).toEqual([
      'best',
      '1080p',
      '720p',
      '360p',
    ])
    expect(select.options[0].textContent).toBe('Best available (1080p)')
  })

  it('offers the real formats of a video with unusual heights', async () => {
    mockApi({
      ...base,
      // A vertical phone recording: nothing lines up with the standard ladder.
      'POST /api/inspect': () =>
        json({
          ...result,
          video_heights: [1920, 886, 640],
          estimated_sizes: { '1920': 524_288_000, '886': 104_857_600, '640': 52_428_800 },
        }),
      'POST /api/preview': () => json(preview),
    })
    renderApp('/download/other')

    await inspectUrl()

    const select = (await screen.findByLabelText('Quality')) as HTMLSelectElement
    // One option per real format, each naming the height that quality really gets,
    // and no step that would select nothing or repeat a format.
    expect([...select.options].map((option) => option.textContent)).toEqual([
      'Best available (1920p · ≈ 500 MB)',
      '2160p → 1920p · ≈ 500 MB',
      '1080p → 886p · ≈ 100 MB',
      '720p → 640p · ≈ 50 MB',
    ])
    expect([...select.options].map((option) => option.value)).toEqual([
      'best',
      '2160p',
      '1080p',
      '720p',
    ])
  })

  it('is reachable from Home', async () => {
    mockApi(base)
    renderApp('/')

    fireEvent.click(await screen.findByRole('link', { name: /Other/ }))

    expect(await screen.findByRole('heading', { name: 'Download Other' })).toBeInTheDocument()
  })
})

describe('Other wizard transcoding', () => {
  function mockDownload() {
    return mockApi({
      ...base,
      'POST /api/inspect': () => json(result),
      'POST /api/preview': () => json(preview),
      'POST /api/requests': () => json({ id: 'r1', jobs: ['j1'] }, 201),
      'GET /api/jobs': () => json({ jobs: [] }),
    })
  }

  it('leaves transcoding off unless it is picked', async () => {
    const fetchMock = mockDownload()
    mockEventSource()
    renderApp('/download/other')

    await inspectUrl()
    fireEvent.click(await screen.findByText('Advanced'))

    // Off is what the control starts on, and the quality field stays out of the way.
    expect(await screen.findByLabelText('Transcode')).toHaveValue('off')
    expect(screen.queryByLabelText('Transcode quality')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Download' }))
    await screen.findByRole('heading', { name: 'Queue' })
    const [body] = sentBodies(fetchMock, 'POST /api/requests') as {
      options: { transcode: string; transcode_quality: number | null }
    }[]
    expect(body.options.transcode).toBe('off')
    expect(body.options.transcode_quality).toBeNull()
  })

  it('offers a transcode profile and sends it with the request', async () => {
    const fetchMock = mockDownload()
    mockEventSource()
    renderApp('/download/other')

    await inspectUrl()
    fireEvent.click(await screen.findByText('Advanced'))
    const profiles = await screen.findByLabelText('Transcode')
    expect([...profiles.querySelectorAll('option')].map((o) => o.value)).toEqual([
      'off',
      'hevc-qsv',
      'hevc-vaapi',
      'x265-software',
    ])

    fireEvent.change(profiles, { target: { value: 'hevc-qsv' } })
    fireEvent.change(await screen.findByLabelText('Transcode quality'), {
      target: { value: '22' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Download' }))

    await screen.findByRole('heading', { name: 'Queue' })
    const [body] = sentBodies(fetchMock, 'POST /api/requests') as {
      options: { transcode: string; transcode_quality: number | null }
    }[]
    expect(body.options.transcode).toBe('hevc-qsv')
    expect(body.options.transcode_quality).toBe(22)
  })

  it('leaves the quality empty so the Settings default is used', async () => {
    const fetchMock = mockDownload()
    mockEventSource()
    renderApp('/download/other')

    await inspectUrl()
    fireEvent.click(await screen.findByText('Advanced'))
    fireEvent.change(await screen.findByLabelText('Transcode'), {
      target: { value: 'x265-software' },
    })

    expect(await screen.findByLabelText('Transcode quality')).toHaveAttribute(
      'placeholder',
      'Settings default',
    )
    fireEvent.click(screen.getByRole('button', { name: 'Download' }))
    await screen.findByRole('heading', { name: 'Queue' })
    const [body] = sentBodies(fetchMock, 'POST /api/requests') as {
      options: { transcode: string; transcode_quality: number | null }
    }[]
    expect(body.options.transcode).toBe('x265-software')
    expect(body.options.transcode_quality).toBeNull()
  })
})

describe('Other wizard: download again', () => {
  it('prefills url and options from a previous request', async () => {
    const earlier: RequestRead = {
      id: 'req-1',
      media_type: 'other',
      title: 'Big Buck Bunny',
      year: null,
      numbering: null,
      radarr_movie_id: null,
      sonarr_series_id: null,
      // Stored before transcoding existed: the missing fields fall back to the defaults.
      options: {
        quality: '720p',
        container: 'mp4',
        fragments: 'auto',
        use_aria2c: 'auto',
        retries: 3,
      },
      created_at: '2026-09-01T10:00:00',
      jobs: [{ id: 'job-1', url: URL } as Job],
    }
    const fetchMock = mockApi({
      ...base,
      'GET /api/requests/req-1': () => json(earlier),
      'POST /api/inspect': () => json(result),
      'POST /api/preview': () => json(preview),
      'POST /api/requests': () => json({ id: 'r2', jobs: ['j2'] }, 201),
      'GET /api/jobs': () => json({ jobs: [] }),
    })
    mockEventSource()
    renderApp('/download/other?again=req-1&job=job-1')

    // Inspected on arrival, with nothing typed.
    expect(await screen.findByRole('heading', { name: 'Big Buck Bunny' })).toBeInTheDocument()
    expect(screen.getByLabelText('Video URL')).toHaveValue(URL)
    expect(sentBodies(fetchMock, 'POST /api/inspect')).toEqual([{ url: URL }])

    fireEvent.click(screen.getByRole('button', { name: 'Download' }))

    await screen.findByRole('heading', { name: 'Queue' })
    expect(sentBodies(fetchMock, 'POST /api/requests')).toMatchObject([
      {
        media_type: 'other',
        options: {
          quality: '720p',
          container: 'mp4',
          fragments: 'auto',
          use_aria2c: 'auto',
          retries: 3,
          transcode: 'off',
          transcode_quality: null,
        },
      },
    ])
  })
})

// ------------------------------------------- AC8: the M10a option groups and presets

const WITH_SUBS: InspectResult = {
  ...result,
  subtitles: { en: ['srt'], de: ['vtt'] },
  automatic_captions: { en: ['vtt'] },
  audio_tracks: [
    { lang: 'en', codec: 'opus', abr: 129 },
    { lang: 'ja', codec: 'opus', abr: 129 },
  ],
  has_hdr: true,
}

function preset(overrides: Partial<Preset> = {}): Preset {
  return {
    id: 1,
    name: 'Phone-friendly mp4',
    media_type: 'other',
    options: { quality: '720p', container: 'mp4', rate_limit: '5M' },
    is_default: true,
    ...overrides,
  }
}

describe('Other wizard: subtitles, extras and presets', () => {
  function mockWizard(routes: Record<string, () => Response> = {}) {
    const fetchMock = mockApi({
      ...base,
      'POST /api/inspect': () => json(WITH_SUBS),
      'POST /api/preview': () => json(preview),
      'POST /api/requests': () => json({ id: 'r1', jobs: ['j1'] }, 201),
      'GET /api/jobs': () => json({ jobs: [] }),
      'GET /api/presets': () => json([]),
      ...routes,
    })
    mockEventSource()
    return fetchMock
  }

  it('hides the subtitle, audio and HDR controls when inspect found none', async () => {
    mockWizard({ 'POST /api/inspect': () => json(result) })
    renderApp('/download/other')

    await inspectUrl()
    expect(await screen.findByText(preview.path)).toBeInTheDocument()
    fireEvent.click(screen.getByText('Advanced'))

    expect(screen.queryByLabelText('Subtitles')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Audio track')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Allow HDR')).not.toBeInTheDocument()
    // The options that apply to any video are always there.
    expect(screen.getByLabelText('SponsorBlock')).toBeInTheDocument()
    expect(screen.getByLabelText('Video codec')).toBeInTheDocument()
    expect(screen.getByLabelText('Rate limit')).toBeInTheDocument()
  })

  it('shows the subtitle, audio and HDR controls when inspect found them', async () => {
    mockWizard()
    renderApp('/download/other')

    await inspectUrl()
    expect(await screen.findByText(preview.path)).toBeInTheDocument()

    const mode = screen.getByLabelText('Subtitles')
    expect([...(mode as HTMLSelectElement).options].map((o) => o.value)).toEqual([
      'off',
      'embed',
      'sidecar',
    ])
    const audio = screen.getByLabelText('Audio track') as HTMLSelectElement
    expect([...audio.options].map((o) => o.value)).toEqual(['', 'en', 'ja'])

    // The languages and the auto-caption toggle only appear once a mode is picked.
    expect(screen.queryByLabelText('de')).not.toBeInTheDocument()
    fireEvent.change(mode, { target: { value: 'sidecar' } })
    expect(screen.getByLabelText('de')).toBeInTheDocument()
    expect(screen.getByLabelText('Include auto-captions')).toBeInTheDocument()

    fireEvent.click(screen.getByText('Advanced'))
    expect(screen.getByLabelText('Allow HDR')).toBeInTheDocument()
  })

  it('sends the new options in the request body', async () => {
    const fetchMock = mockWizard()
    renderApp('/download/other')

    await inspectUrl()
    expect(await screen.findByText(preview.path)).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Subtitles'), { target: { value: 'sidecar' } })
    fireEvent.click(screen.getByLabelText('en'))
    fireEvent.click(screen.getByLabelText('Include auto-captions'))
    fireEvent.change(screen.getByLabelText('Audio track'), { target: { value: 'ja' } })
    fireEvent.click(screen.getByText('Advanced'))
    fireEvent.change(screen.getByLabelText('SponsorBlock'), { target: { value: 'remove' } })
    fireEvent.change(screen.getByLabelText('Video codec'), { target: { value: 'h264' } })
    fireEvent.change(screen.getByLabelText('Rate limit'), { target: { value: '5M' } })
    fireEvent.click(screen.getByLabelText('Allow HDR'))
    fireEvent.click(screen.getByRole('button', { name: 'Download' }))

    expect(await screen.findByRole('heading', { name: 'Queue' })).toBeInTheDocument()
    const [body] = sentBodies(fetchMock, 'POST /api/requests') as { options: DownloadOptions }[]
    expect(body.options.subtitles).toEqual({
      mode: 'sidecar',
      languages: ['en'],
      include_auto_captions: true,
    })
    expect(body.options.sponsorblock).toEqual({ mode: 'remove', categories: [] })
    expect(body.options.audio_language).toBe('ja')
    expect(body.options.video_codec).toBe('h264')
    expect(body.options.rate_limit).toBe('5M')
    expect(body.options.allow_hdr).toBe(false)
  })

  it('preselects the default preset and applies it', async () => {
    const fetchMock = mockWizard({ 'GET /api/presets': () => json([preset()]) })
    renderApp('/download/other')

    await inspectUrl()
    expect(await screen.findByText(preview.path)).toBeInTheDocument()

    expect(await screen.findByDisplayValue('mp4')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Download' }))

    expect(await screen.findByRole('heading', { name: 'Queue' })).toBeInTheDocument()
    const [body] = sentBodies(fetchMock, 'POST /api/requests') as { options: DownloadOptions }[]
    expect(body.options.container).toBe('mp4')
    expect(body.options.quality).toBe('720p')
    expect(body.options.rate_limit).toBe('5M')
    // Everything the preset didn't name falls back to the defaults, never to undefined.
    expect(body.options.subtitles).toEqual({
      mode: 'off',
      languages: [],
      include_auto_captions: false,
    })
  })

  it('offers an `any` preset here too, and leaves a non-default one unapplied', async () => {
    mockWizard({
      'GET /api/presets': () =>
        json([
          preset({ id: 2, name: 'Anywhere', media_type: 'any', is_default: false }),
          preset({ id: 3, name: 'Movies only', media_type: 'movie', is_default: true }),
        ]),
    })
    renderApp('/download/other')

    await inspectUrl()
    expect(await screen.findByText(preview.path)).toBeInTheDocument()

    const picker = (await screen.findByLabelText('Preset')) as HTMLSelectElement
    expect([...picker.options].map((o) => o.textContent)).toEqual(['No preset', 'Anywhere'])
    // Nothing was the default for `other`, so the form is still on its own defaults.
    expect(picker.value).toBe('')
    expect(screen.getByLabelText('Container')).toHaveValue('mkv')

    fireEvent.change(picker, { target: { value: '2' } })
    expect(screen.getByLabelText('Container')).toHaveValue('mp4')
  })

  it('keeps download-again options over the default preset', async () => {
    const earlier: RequestRead = {
      id: 'req-1',
      media_type: 'other',
      title: 'Big Buck Bunny',
      year: null,
      numbering: null,
      radarr_movie_id: null,
      sonarr_series_id: null,
      options: { quality: '480p', container: 'mkv' },
      created_at: '2026-09-01T10:00:00',
      jobs: [{ id: 'job-1', url: URL } as Job],
    }
    const fetchMock = mockWizard({
      'GET /api/presets': () => json([preset()]),
      'GET /api/requests/req-1': () => json(earlier),
    })
    renderApp('/download/other?again=req-1&job=job-1')

    expect(await screen.findByText(preview.path)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Download' }))

    expect(await screen.findByRole('heading', { name: 'Queue' })).toBeInTheDocument()
    const [body] = sentBodies(fetchMock, 'POST /api/requests') as { options: DownloadOptions }[]
    expect(body.options.quality).toBe('480p')
    expect(body.options.container).toBe('mkv')
  })

  it('saves the current options as a preset', async () => {
    const fetchMock = mockWizard({
      'POST /api/presets': () => json(preset({ id: 9, name: 'My preset' }), 201),
    })
    renderApp('/download/other')

    await inspectUrl()
    expect(await screen.findByText(preview.path)).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Quality'), { target: { value: '1080p' } })
    fireEvent.change(screen.getByLabelText('Save as preset'), { target: { value: 'My preset' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(sentBodies(fetchMock, 'POST /api/presets')).toEqual([
        {
          name: 'My preset',
          media_type: 'other',
          options: { ...DEFAULT_OPTIONS, quality: '1080p' },
        },
      ]),
    )
  })
})
