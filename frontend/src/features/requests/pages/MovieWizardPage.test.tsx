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
    {
      id: 7,
      title: 'Big Buck Bunny',
      year: 2008,
      monitored: true,
      has_file: false,
      quality: null,
      poster: 'https://image.tmdb.org/bbb.jpg',
    },
    {
      id: 11,
      title: 'The Big Lebowski',
      year: 1998,
      monitored: true,
      has_file: false,
      quality: null,
      poster: null,
    },
  ],
}

const MISSING = {
  movies: [
    {
      id: 9,
      title: 'Sintel',
      year: 2010,
      monitored: true,
      has_file: false,
      quality: null,
      poster: 'https://image.tmdb.org/sintel.jpg',
    },
    // No poster in Radarr: the row still has to render.
    {
      id: 13,
      title: 'Big Fish',
      year: 2003,
      monitored: true,
      has_file: false,
      quality: null,
      poster: null,
    },
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
    'GET /api/arr/radarr/movies?q=&missing=true': () => json(MISSING),
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

async function pickMissing(name: string) {
  const list = await screen.findByRole('list', { name: 'Missing movies' })
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
            {
              id: 7,
              title: 'Big Buck Bunny',
              year: 2008,
              monitored: true,
              has_file: true,
              quality: 'WEBDL-720p',
              poster: null,
            },
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

  it('opens on Paste a URL', async () => {
    mockWizard()
    renderApp('/download/movie')

    // The M5b way in is still the default, so nothing an existing owner does changes.
    expect(await screen.findByRole('tab', { name: 'Paste a URL' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(screen.getByRole('tab', { name: 'Missing in Radarr' })).toHaveAttribute(
      'aria-selected',
      'false',
    )
    expect(screen.getByLabelText('Video URL')).toBeInTheDocument()
  })

  it("lists the movies Radarr is missing and downloads one against Radarr's own title", async () => {
    const fetchMock = mockWizard()
    mockEventSource()
    renderApp('/download/movie')

    fireEvent.click(await screen.findByRole('tab', { name: 'Missing in Radarr' }))

    const list = await screen.findByRole('list', { name: 'Missing movies' })
    expect(within(list).getByRole('button', { name: 'Big Fish (2003)' })).toBeInTheDocument()
    // Radarr's poster, decorative so it stays out of the button's accessible name (AC11).
    const poster = within(list).getByRole('presentation', { hidden: true })
    expect(poster).toHaveAttribute('src', 'https://image.tmdb.org/sintel.jpg')
    // The URL is only asked for once a movie has been picked.
    expect(screen.queryByLabelText('Video URL')).not.toBeInTheDocument()

    await pickMissing('Sintel (2010)')

    // The poster stays with the movie once picked, beside the URL form (AC11).
    expect(screen.getByRole('presentation', { hidden: true })).toHaveAttribute(
      'src',
      'https://image.tmdb.org/sintel.jpg',
    )

    await inspectUrl()

    expect(await screen.findByText(PATH)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Download' }))

    expect(await screen.findByRole('heading', { name: 'Queue' })).toBeInTheDocument()
    // Radarr's own id, title and year, exactly as the URL-first tab sends them.
    expect(sentBodies(fetchMock, 'POST /api/requests')).toEqual([
      {
        media_type: 'movie',
        media: { radarr_movie_id: 9, title: 'Sintel', year: 2010 },
        items: [{ inspection_id: 7 }],
        options: OPTIONS,
        collision_policy: 'keep_both',
      },
    ])
    expect(sentBodies(fetchMock, 'POST /api/preview')).toContainEqual({
      media_type: 'movie',
      media: { radarr_movie_id: 9, title: 'Sintel', year: 2010 },
      inspection_id: 7,
      options: OPTIONS,
    })
  })

  it('clears the picked movie when the tab changes', async () => {
    const fetchMock = mockWizard()
    renderApp('/download/movie')

    fireEvent.click(await screen.findByRole('tab', { name: 'Missing in Radarr' }))
    await pickMissing('Sintel (2010)')
    expect(await screen.findByLabelText('Video URL')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('tab', { name: 'Paste a URL' }))
    await inspectUrl()

    // Sintel didn't come along, so nothing is previewed and nothing can be sent.
    expect(await screen.findByText(/pick the movie first/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Download' })).toBeDisabled()
    expect(sentBodies(fetchMock, 'POST /api/preview')).toEqual([])
  })

  it('refreshes the missing list straight from Radarr', async () => {
    const refreshed = {
      movies: [
        {
          id: 21,
          title: 'Tears of Steel',
          year: 2012,
          monitored: true,
          has_file: false,
          quality: null,
          poster: null,
        },
      ],
    }
    const fetchMock = mockWizard({
      'GET /api/arr/radarr/movies?q=&missing=true&refresh=true': () => json(refreshed),
    })
    renderApp('/download/movie')

    fireEvent.click(await screen.findByRole('tab', { name: 'Missing in Radarr' }))
    await screen.findByRole('button', { name: 'Sintel (2010)' })

    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }))

    // Radarr's library is cached for five minutes; Refresh is the way past it.
    expect(await screen.findByRole('button', { name: 'Tears of Steel (2012)' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Sintel (2010)' })).not.toBeInTheDocument()
    expect(
      fetchMock.mock.calls.filter(
        ([input]) => String(input) === '/api/arr/radarr/movies?q=&missing=true&refresh=true',
      ),
    ).toHaveLength(1)
  })

  it('shows Radarr posters in the Paste a URL tab too', async () => {
    mockWizard()
    renderApp('/download/movie')

    await inspectUrl()

    const list = await screen.findByRole('list', { name: 'Radarr movies' })
    // Same decorative poster treatment as the Missing tab, so the two ways in match.
    const posters = within(list).getAllByRole('presentation', { hidden: true })
    expect(posters[0]).toHaveAttribute('src', 'https://image.tmdb.org/bbb.jpg')
    // The poster must stay out of the accessible name, or picking by title breaks.
    expect(within(list).getByRole('button', { name: 'Big Buck Bunny (2008)' })).toBeInTheDocument()

    await pick('Big Buck Bunny (2008)')

    expect(screen.getByRole('presentation', { hidden: true })).toHaveAttribute(
      'src',
      'https://image.tmdb.org/bbb.jpg',
    )
  })

  it('is reachable from Home', async () => {
    mockApi(base)
    renderApp('/')

    fireEvent.click(await screen.findByRole('link', { name: /Movie/ }))

    expect(await screen.findByRole('heading', { name: 'Download Movie' })).toBeInTheDocument()
  })
})
