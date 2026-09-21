import { fireEvent, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { InspectResult } from '@/features/inspections'
import { json, mockApi, mockEventSource, renderApp, sentBodies } from '@/test/mockApi'

const base = {
  'GET /api/auth/me': () => json({ username: 'owner' }),
  'GET /healthz': () => json({ status: 'ok', version: '1.2.3' }),
}

const URL = 'https://www.youtube.com/watch?v=aqz-KE-bpKQ'

const result: InspectResult = {
  inspection_id: 7,
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
        },
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
