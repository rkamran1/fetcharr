import { fireEvent, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { InspectResult } from '@/features/inspections'
import { json, mockApi, renderApp } from '@/test/mockApi'

const URL = 'https://www.youtube.com/watch?v=aqz-KE-bpKQ'

const result: InspectResult = {
  inspection_id: 7,
  site_key: 'youtube',
  title: 'Big Buck Bunny',
  uploader: 'Blender',
  thumbnail: null,
  duration: 635,
  webpage_url: URL,
  extractor: 'youtube',
  id: 'aqz-KE-bpKQ',
  upload_date: '20141110',
  release_year: 2014,
  video_heights: [1080, 720],
  video_codecs: ['avc1'],
  audio_tracks: [{ lang: null, codec: 'opus', abr: 129 }],
  has_hdr: false,
  subtitles: {},
  automatic_captions: {},
  estimated_sizes: { '1080': 137254097 },
  stream_type: 'dash',
  auto: { fragments: 4, use_aria2c: false },
}

const base = {
  'GET /api/auth/me': () => json({ username: 'owner' }),
  'GET /healthz': () => json({ status: 'ok', version: '1.2.3' }),
  'POST /api/inspect': () => json(result),
  'POST /api/preview': () => json({ path: '/web-downloads/completed/other/Big Buck Bunny.mkv' }),
}

function link(name: string): HTMLElement {
  return screen.getByRole('link', { name: new RegExp(name) })
}

const query = `url=${encodeURIComponent(URL)}`

describe('SharePage (AC7)', () => {
  it('offers the three types for a shared url', async () => {
    mockApi(base)
    renderApp(`/share?${query}`)

    expect(await screen.findByText(URL)).toBeInTheDocument()
    expect(link('Movie')).toHaveAttribute('href', `/download/movie?${query}`)
    expect(link('TV Show')).toHaveAttribute('href', `/download/tv?${query}`)
    expect(link('Other')).toHaveAttribute('href', `/download/other?${query}`)
  })

  it('reads the url out of the text param', async () => {
    mockApi(base)
    renderApp(`/share?text=${encodeURIComponent(`Watch this ${URL} it is short`)}`)

    expect(await screen.findByText(URL)).toBeInTheDocument()
    expect(link('Other')).toHaveAttribute('href', `/download/other?${query}`)
  })

  it('still offers the wizards when no link came through', async () => {
    mockApi(base)
    renderApp('/share')

    expect(await screen.findByRole('alert')).toHaveTextContent('No link came through')
    expect(link('Other')).toHaveAttribute('href', '/download/other')
  })

  it('hands the url to the Other wizard, which inspects it', async () => {
    const fetchMock = mockApi(base)
    renderApp(`/share?${query}`)

    fireEvent.click(await screen.findByRole('link', { name: /Other/ }))

    expect(await screen.findByLabelText('Video URL')).toHaveValue(URL)
    expect(await screen.findByRole('heading', { name: 'Big Buck Bunny' })).toBeInTheDocument()
    expect(fetchMock.mock.calls.filter(([path]) => path === '/api/inspect')).toHaveLength(1)
  })

  it('hands the url to the Movie wizard, which inspects it', async () => {
    mockApi({ ...base, 'GET /api/arr/radarr/movies': () => json({ movies: [] }) })
    renderApp(`/download/movie?${query}`)

    expect(await screen.findByRole('heading', { name: 'Big Buck Bunny' })).toBeInTheDocument()
  })
})
