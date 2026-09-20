import { fireEvent, screen, waitFor, within } from '@testing-library/react'
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
  title: 'Big Buck Bunny (Official Full Movie) [4K]',
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
  audio_tracks: [],
  has_hdr: false,
  subtitles: {},
  automatic_captions: {},
  estimated_sizes: {},
  stream_type: 'http',
  auto: { fragments: 1, use_aria2c: false },
}

const MOVIES = {
  movies: [
    { id: 7, title: 'Big Buck Bunny', year: 2008, has_file: false, quality: null },
    { id: 11, title: 'The Big Lebowski', year: 1998, has_file: false, quality: null },
  ],
}

const PATH =
  '/web-downloads/completed/movies/Big Buck Bunny (2008)/Big Buck Bunny (2008) WEBDL-1080p.mkv'

const OPTIONS = {
  quality: 'best',
  container: 'mkv',
  fragments: 'auto',
  use_aria2c: 'auto',
  retries: 5,
}

function mockWizard(overrides: Record<string, () => Response> = {}) {
  return mockApi({
    ...base,
    'POST /api/inspect': () => json(result),
    'GET /api/arr/radarr/movies?q=Big%20Buck%20Bunny': () => json(MOVIES),
    'POST /api/preview': () => json({ path: PATH, exists: false }),
    'POST /api/requests': () => json({ id: 'r1', jobs: ['j1'] }, 201),
    'GET /api/jobs': () => json({ jobs: [] }),
    ...overrides,
  })
}

async function inspectUrl() {
  fireEvent.change(await screen.findByLabelText('Video URL'), { target: { value: URL } })
  fireEvent.click(screen.getByRole('button', { name: 'Inspect' }))
}

async function pick(name: string) {
  const list = await screen.findByRole('list', { name: 'Radarr movies' })
  fireEvent.click(within(list).getByRole('button', { name }))
}

describe('Movie wizard', () => {
  it('prefills the Radarr search from the cleaned video title and sends what Radarr calls it', async () => {
    const fetchMock = mockWizard()
    mockEventSource()
    renderApp('/download/movie')

    await inspectUrl()

    // "(Official Full Movie)" and "[4K]" are noise a Radarr search doesn't want (§5 step 2a).
    expect(await screen.findByLabelText('Movie in Radarr')).toHaveValue('Big Buck Bunny')
    await pick('Big Buck Bunny (2008)')
    expect(await screen.findByText(PATH)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Download' }))

    expect(await screen.findByRole('heading', { name: 'Queue' })).toBeInTheDocument()
    expect(sentBodies(fetchMock, 'POST /api/requests')).toEqual([
      {
        media_type: 'movie',
        media: { radarr_movie_id: 7, title: 'Big Buck Bunny', year: 2008 },
        items: [{ inspection_id: 7 }],
        options: OPTIONS,
        collision_policy: 'keep_both',
      },
    ])
    expect(sentBodies(fetchMock, 'POST /api/preview')).toContainEqual({
      media_type: 'movie',
      media: { radarr_movie_id: 7, title: 'Big Buck Bunny', year: 2008 },
      inspection_id: 7,
      options: OPTIONS,
    })
  })

  it('notes that Radarr already has a file', async () => {
    mockWizard({
      'GET /api/arr/radarr/movies?q=Big%20Buck%20Bunny': () =>
        json({
          movies: [
            { id: 7, title: 'Big Buck Bunny', year: 2008, has_file: true, quality: 'WEBDL-720p' },
          ],
        }),
    })
    renderApp('/download/movie')

    await inspectUrl()
    await pick('Big Buck Bunny (2008)')

    expect(
      await screen.findByText(/Radarr already has this at WEBDL-720p/),
    ).toBeInTheDocument()
  })

  it('warns when the movie is typed by hand', async () => {
    const fetchMock = mockWizard()
    mockEventSource()
    renderApp('/download/movie')

    await inspectUrl()
    fireEvent.click(await screen.findByRole('button', { name: "It's not in Radarr" }))
    fireEvent.change(screen.getByLabelText('Movie title'), {
      target: { value: 'Some Home Movie' },
    })
    fireEvent.change(screen.getByLabelText('Year'), { target: { value: '2019' } })

    expect(screen.getByRole('alert')).toHaveTextContent(
      "Radarr doesn't have this movie, so the import will fail. Add it in Radarr first " +
        '(then Retry import), or download as Other.',
    )

    fireEvent.click(screen.getByRole('button', { name: 'Download' }))

    await waitFor(() =>
      expect(sentBodies(fetchMock, 'POST /api/requests')).toEqual([
        {
          media_type: 'movie',
          media: { radarr_movie_id: null, title: 'Some Home Movie', year: 2019 },
          items: [{ inspection_id: 7 }],
          options: OPTIONS,
          collision_policy: 'keep_both',
        },
      ]),
    )
  })

  it('asks Replace or Keep both when a file is already there', async () => {
    const fetchMock = mockWizard({
      'POST /api/preview': () => json({ path: PATH, exists: true }),
    })
    mockEventSource()
    renderApp('/download/movie')

    await inspectUrl()
    await pick('Big Buck Bunny (2008)')

    expect(
      await screen.findByText('An un-imported file for this already exists in completed/'),
    ).toBeInTheDocument()
    // Nothing is sent until the owner has decided (§7.3).
    expect(screen.getByRole('button', { name: 'Download' })).toBeDisabled()

    fireEvent.click(screen.getByRole('radio', { name: 'Replace' }))
    expect(screen.getByRole('button', { name: 'Download' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'Download' }))

    await waitFor(() =>
      expect(sentBodies(fetchMock, 'POST /api/requests')).toEqual([
        {
          media_type: 'movie',
          media: { radarr_movie_id: 7, title: 'Big Buck Bunny', year: 2008 },
          items: [{ inspection_id: 7 }],
          options: OPTIONS,
          collision_policy: 'replace',
        },
      ]),
    )
  })

  it('waits for a movie before previewing anything', async () => {
    const fetchMock = mockWizard()
    renderApp('/download/movie')

    await inspectUrl()

    expect(await screen.findByText(/pick the movie first/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Download' })).toBeDisabled()
    expect(sentBodies(fetchMock, 'POST /api/preview')).toEqual([])
  })

  it('is reachable from Home', async () => {
    mockApi(base)
    renderApp('/')

    fireEvent.click(await screen.findByRole('link', { name: /Movie/ }))

    expect(await screen.findByRole('heading', { name: 'Download Movie' })).toBeInTheDocument()
  })
})
