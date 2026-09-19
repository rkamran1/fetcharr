import { fireEvent, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { InspectResult } from '@/api/client'
import { json, mockApi, renderApp, sentBodies } from '@/test/mockApi'

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

async function inspectUrl(url = URL) {
  fireEvent.change(await screen.findByLabelText('Video URL'), { target: { value: url } })
  fireEvent.click(screen.getByRole('button', { name: 'Inspect' }))
}

describe('InspectCard on the Inspect page', () => {
  it('shows a loading state while inspecting', async () => {
    mockApi({ ...base, 'POST /api/inspect': () => new Promise<Response>(() => {}) })
    renderApp('/inspect')

    await inspectUrl()

    expect(await screen.findByRole('status')).toHaveTextContent('Inspecting…')
    expect(screen.getByRole('button', { name: 'Inspect' })).toBeDisabled()
  })

  it('shows the inspected video', async () => {
    const fetchMock = mockApi({ ...base, 'POST /api/inspect': () => json(result) })
    renderApp('/inspect')

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
        json({ detail: "Playlists aren't supported, paste a single video URL.", needs_cookies: false }, 422),
    })
    renderApp('/inspect')

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
    renderApp('/inspect')

    await inspectUrl()

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('This video needs cookies.')
    expect(alert).toHaveTextContent('Sign in to confirm your age.')
  })

  it('is reachable from the nav', async () => {
    mockApi(base)
    renderApp('/')

    fireEvent.click(await screen.findByRole('link', { name: 'Inspect' }))

    expect(await screen.findByRole('heading', { name: 'Inspect' })).toBeInTheDocument()
  })
})
