import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { SonarrEpisode, SonarrSeries } from '@/features/arr'
import type { InspectResult } from '@/features/inspections'
import type { Job } from '@/features/jobs'
import { json, mockApi, renderApp, sentBodies } from '@/test/mockApi'

import type { RequestRead } from '../types'

const base = {
  'GET /api/auth/me': () => json({ username: 'owner' }),
  'GET /healthz': () => json({ status: 'ok', version: '1.2.3' }),
}

const URL = 'https://www.youtube.com/watch?v=ep2'

/** Specials complete, season 1 short of three, season 2 short of one. */
const SERIES: SonarrSeries = {
  id: 3,
  title: 'Some Show',
  series_type: 'standard',
  monitored: true,
  seasons: [
    { number: 0, episode_file_count: 2, episode_count: 2, total_episode_count: 2 },
    { number: 1, episode_file_count: 1, episode_count: 4, total_episode_count: 4 },
    { number: 2, episode_file_count: 3, episode_count: 4, total_episode_count: 4 },
  ],
  poster: 'https://artworks.thetvdb.com/some-show.jpg',
}

const DAILY: SonarrSeries = {
  id: 5,
  title: 'Daily Show',
  series_type: 'daily',
  monitored: false,
  seasons: [{ number: 2024, episode_file_count: 0, episode_count: 0, total_episode_count: 2 }],
  poster: null,
}

function episode(number: number, overrides: Partial<SonarrEpisode> = {}): SonarrEpisode {
  return {
    id: 100 + number,
    season: 1,
    number,
    title: `Episode ${number}`,
    air_date: null,
    has_file: false,
    quality: null,
    ...overrides,
  }
}

const SEASON_1 = [
  episode(1, { has_file: true, quality: 'WEBDL-720p', air_date: '2024-03-01' }),
  episode(2, { air_date: '2024-03-08' }),
  episode(3, { air_date: '2024-03-15' }),
  episode(4, { air_date: '2024-03-22' }),
]

const SEASON_2 = [{ ...episode(1, { air_date: '2024-09-01' }), id: 201, season: 2 }]

const DAILY_EPISODES = [
  { ...episode(1, { air_date: '2024-03-14' }), id: 211, season: 2024, title: 'Thursday' },
  { ...episode(2, { air_date: '2024-03-15' }), id: 212, season: 2024, title: 'Friday' },
]

const PATH =
  '/web-downloads/completed/tv-shows/Some Show/Season 1/Some Show - S01E02 - Episode 2 WEBDL-1080p.mkv'

const OPTIONS = {
  quality: 'best',
  container: 'mkv',
  fragments: 'auto',
  use_aria2c: 'auto',
  retries: 5,
  // Transcoding is opt-in, so every wizard sends it off unless it was picked (AC15).
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
}

/** A 720p-only video, so the quality choices can be told apart from a guess (AC20). */
const SMALL: InspectResult = {
  inspection_id: 9,
  site_key: null,
  title: 'a smaller upload',
  uploader: 'Some Channel',
  thumbnail: null,
  duration: 900,
  webpage_url: 'https://www.youtube.com/watch?v=small',
  extractor: 'youtube',
  id: 'small',
  upload_date: '20240308',
  release_year: 2024,
  video_heights: [720],
  video_codecs: ['avc1'],
  audio_tracks: [],
  has_hdr: false,
  subtitles: {},
  automatic_captions: {},
  estimated_sizes: {},
  stream_type: 'http',
  auto: { fragments: 1, use_aria2c: false },
}

const INSPECTION: InspectResult = {
  inspection_id: 7,
  site_key: null,
  title: 'some show s01e02',
  uploader: 'Some Channel',
  thumbnail: null,
  duration: 1500,
  webpage_url: URL,
  extractor: 'youtube',
  id: 'ep2',
  upload_date: '20240308',
  release_year: 2024,
  video_heights: [1080],
  video_codecs: ['avc1'],
  audio_tracks: [],
  has_hdr: false,
  subtitles: {},
  automatic_captions: {},
  estimated_sizes: {},
  stream_type: 'http',
  auto: { fragments: 1, use_aria2c: false },
}

function mockSeries(overrides: Record<string, () => Response> = {}) {
  return mockApi({
    ...base,
    'GET /api/arr/sonarr/series?q=': () => json({ series: [SERIES, DAILY] }),
    'GET /api/arr/sonarr/series/3/episodes?season=1': () => json({ episodes: SEASON_1 }),
    'GET /api/arr/sonarr/series/3/episodes?season=2': () => json({ episodes: SEASON_2 }),
    'GET /api/arr/sonarr/series/5/episodes?season=2024': () => json({ episodes: DAILY_EPISODES }),
    // Answers per URL, so two rows can be inspected into different formats (AC20).
    'POST /api/inspect': (init) => {
      const body = JSON.parse(String(init?.body)) as { url: string }
      return json(body.url.includes('small') ? SMALL : INSPECTION)
    },
    'POST /api/preview': () => json({ path: PATH, exists: false }),
    'POST /api/requests': () => json({ id: 'r1', jobs: ['j1'] }, 201),
    ...overrides,
  })
}

function seasons() {
  return within(screen.getByRole('list', { name: 'Seasons' })).getAllByRole('listitem')
}

/** Open one season's section and hand back a scope for what is inside it. */
async function openSeason(label: string) {
  const toggle = await screen.findByRole('button', { name: new RegExp(`^${label}`) })
  fireEvent.click(toggle)
  return within(toggle.closest('li')!)
}

/** Paste a URL into one episode's row and press its own Inspect (AC20). */
async function inspectRow(label: string, url = URL) {
  const field = await screen.findByLabelText(`Video URL for ${label}`)
  fireEvent.change(field, { target: { value: url } })
  const form = field.closest('form')!
  fireEvent.click(within(form).getByRole('button', { name: 'Inspect' }))
  return { field, row: within(form.parentElement!) }
}

/** The quality dropdown's options, which come from the inspected video (§5 step 2d). */
function qualities(row: ReturnType<typeof within>): (string | null)[] {
  return [...row.getByLabelText('Quality').querySelectorAll('option')].map((o) => o.textContent)
}

describe("a series' own page (AC18)", () => {
  it("lists the series' seasons as collapsed sections", async () => {
    mockSeries()
    renderApp('/download/tv/3')

    expect(await screen.findByRole('heading', { name: 'Some Show' })).toBeInTheDocument()

    // Specials is complete, so it isn't offered; the other two say what they are short of.
    await waitFor(() => expect(seasons()).toHaveLength(2))
    expect(seasons().map((item) => within(item).getByRole('button').textContent?.slice(1))).toEqual(
      ['Season 13 missing', 'Season 21 missing'],
    )
    // Collapsed: nothing to type into, and no episode request made yet.
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    expect(within(seasons()[0]).getByRole('button')).toHaveAttribute('aria-expanded', 'false')
  })

  it('opens a season to reveal its missing episodes', async () => {
    mockSeries()
    renderApp('/download/tv/3')

    const first = await openSeason('Season 1')

    // Episode 1 has a file, so only the three gaps are listed, each with its own URL.
    expect(
      await first.findByLabelText('Video URL for S01E02 · Episode 2 · 2024-03-08'),
    ).toBeInTheDocument()
    expect(first.getAllByRole('button', { name: 'Inspect' })).toHaveLength(3)
    // Nothing is downloadable, and no options are offered, until a link is inspected.
    expect(first.queryByRole('button', { name: 'Download' })).not.toBeInTheDocument()
    expect(first.queryByLabelText('Quality')).not.toBeInTheDocument()
    expect(first.queryByText(/^S01E01/)).not.toBeInTheDocument()
    // The other season stays shut.
    expect(within(seasons()[1]).getByRole('button')).toHaveAttribute('aria-expanded', 'false')
  })

  it("fetches a season's episodes only when it is opened", async () => {
    const fetchMock = mockSeries()
    renderApp('/download/tv/3')

    await waitFor(() => expect(seasons()).toHaveLength(2))
    const episodeCalls = () =>
      fetchMock.mock.calls.filter(([input]) => String(input).includes('/episodes?'))
    // Two seasons on screen, neither opened: no episode request at all.
    expect(episodeCalls()).toHaveLength(0)

    await openSeason('Season 2')

    await waitFor(() => expect(episodeCalls()).toHaveLength(1))
    expect(String(episodeCalls()[0][0])).toContain('season=2')
  })

  it('names a daily episode by its air date', async () => {
    mockSeries()
    renderApp('/download/tv/5')

    const season = await openSeason('Season 2024')

    // A daily series is numbered by date, so that is what the row leads with (§7.2).
    expect(await season.findByText('2024-03-14 · Thursday')).toBeInTheDocument()
    expect(season.getByText('2024-03-15 · Friday')).toBeInTheDocument()
    // And the page repeats why Sonarr won't fill it on its own.
    expect(screen.getByText(/Not monitored in Sonarr/)).toBeInTheDocument()
  })

  it('shows the episodes Sonarr already has only when asked', async () => {
    mockSeries()
    renderApp('/download/tv/3')

    const first = await openSeason('Season 1')
    expect(await first.findByText(/^S01E02/)).toBeInTheDocument()
    expect(first.queryByText(/^S01E01/)).not.toBeInTheDocument()

    fireEvent.click(screen.getByLabelText('Show episodes Sonarr already has'))

    // Present, and saying what Sonarr holds, so a file can be replaced (§7.5).
    expect(await first.findByText(/^S01E01/)).toBeInTheDocument()
    expect(first.getByText('Sonarr has WEBDL-720p')).toBeInTheDocument()
    // A complete season becomes reachable too.
    expect(seasons()).toHaveLength(3)
  })
})

describe('downloading one episode (AC19)', () => {
  const label = 'S01E02 · Episode 2 · 2024-03-08'

  it('downloads one episode and keeps you on the page', async () => {
    const fetchMock = mockSeries()
    renderApp('/download/tv/3')

    await openSeason('Season 1')
    const { row } = await inspectRow(label)

    fireEvent.click(await row.findByRole('button', { name: 'Download' }))

    expect(await row.findByText(/^Queued\./)).toHaveTextContent(PATH)
    // One request, for exactly this episode, with Sonarr's own words (§7.2).
    expect(sentBodies(fetchMock, 'POST /api/requests')).toEqual([
      {
        media_type: 'tv',
        media: { sonarr_series_id: 3, title: 'Some Show', numbering: 'standard' },
        items: [
          {
            inspection_id: 7,
            episode: {
              season: 1,
              number: 2,
              sonarr_episode_id: 102,
              title: 'Episode 2',
              air_date: '2024-03-08',
            },
          },
        ],
        options: OPTIONS,
        collision_policy: 'keep_both',
        use_cookies: true,
      },
    ])
    // Still here, with the next gap ready and the other season untouched.
    expect(screen.getByRole('heading', { name: 'Some Show' })).toBeInTheDocument()
    expect(
      screen.getByLabelText('Video URL for S01E03 · Episode 3 · 2024-03-15'),
    ).toBeInTheDocument()
    expect(within(seasons()[1]).getByRole('button')).toHaveAttribute('aria-expanded', 'false')
  })

  it('asks before replacing an un-imported file', async () => {
    const fetchMock = mockSeries({
      'POST /api/preview': () => json({ path: PATH, exists: true }),
    })
    renderApp('/download/tv/3')

    await openSeason('Season 1')
    const { row } = await inspectRow(label)

    // Nothing is queued while the question stands (§7.3).
    expect(
      await row.findByText(/An un-imported file for this episode already exists/),
    ).toBeInTheDocument()
    expect(row.getByRole('button', { name: 'Download' })).toBeDisabled()

    fireEvent.click(row.getByLabelText('Replace'))
    fireEvent.click(row.getByRole('button', { name: 'Download' }))

    await waitFor(() => expect(sentBodies(fetchMock, 'POST /api/requests')).toHaveLength(1))
    const [body] = sentBodies(fetchMock, 'POST /api/requests') as [{ collision_policy: string }]
    expect(body.collision_policy).toBe('replace')
  })

  it('posts a daily episode with its air date and daily numbering', async () => {
    const fetchMock = mockSeries()
    renderApp('/download/tv/5')

    await openSeason('Season 2024')
    const { row } = await inspectRow('2024-03-15 · Friday')

    fireEvent.click(await row.findByRole('button', { name: 'Download' }))

    await waitFor(() => expect(sentBodies(fetchMock, 'POST /api/requests')).toHaveLength(1))
    const [body] = sentBodies(fetchMock, 'POST /api/requests') as [
      { media: unknown; items: { episode: unknown }[] },
    ]
    expect(body.media).toEqual({ sonarr_series_id: 5, title: 'Daily Show', numbering: 'daily' })
    expect(body.items[0].episode).toEqual({
      season: 2024,
      number: 2,
      sonarr_episode_id: 212,
      title: 'Friday',
      air_date: '2024-03-15',
    })
  })
})

describe('one link, its own inspect and its own options (AC20)', () => {
  const label = 'S01E02 · Episode 2 · 2024-03-08'
  const other = 'S01E03 · Episode 3 · 2024-03-15'

  it('inspects one link and offers the options that video really has', async () => {
    const fetchMock = mockSeries()
    renderApp('/download/tv/3')

    await openSeason('Season 1')
    const { row } = await inspectRow(label, 'https://www.youtube.com/watch?v=small')

    // What yt-dlp found for this link, not a guess made by the page.
    expect(await row.findByRole('heading', { name: 'a smaller upload' })).toBeInTheDocument()
    expect(within(row.getByRole('list', { name: 'Qualities' })).getByText('720p')).toBeVisible()
    // A 720p upload offers 720p and nothing above it (§5 step 2d).
    expect(qualities(row)).toEqual(['Best available (720p)', '720p'])
    // Exactly one URL was inspected: the one in this row.
    expect(sentBodies(fetchMock, 'POST /api/inspect')).toEqual([
      { url: 'https://www.youtube.com/watch?v=small' },
    ])
  })

  it("keeps each row's options to itself", async () => {
    const fetchMock = mockSeries()
    renderApp('/download/tv/3')

    await openSeason('Season 1')
    const first = await inspectRow(label)
    await first.row.findByLabelText('Quality')
    const second = await inspectRow(other, 'https://www.youtube.com/watch?v=small')
    await second.row.findByLabelText('Quality')

    // The 1080p link and the 720p link offer different choices, side by side.
    expect(qualities(first.row)).toEqual(['Best available (1080p)', '1080p'])
    expect(qualities(second.row)).toEqual(['Best available (720p)', '720p'])

    fireEvent.change(first.row.getByLabelText('Container'), { target: { value: 'mp4' } })

    // Changing one leaves its neighbour alone, and what is posted is the row's own.
    expect(second.row.getByLabelText('Container')).toHaveValue('mkv')
    fireEvent.click(first.row.getByRole('button', { name: 'Download' }))
    await waitFor(() => expect(sentBodies(fetchMock, 'POST /api/requests')).toHaveLength(1))
    const [body] = sentBodies(fetchMock, 'POST /api/requests') as [
      { options: { container: string } },
    ]
    expect(body.options.container).toBe('mp4')
  })

  it('shows why an inspect failed and keeps the URL', async () => {
    mockSeries({
      'POST /api/inspect': () => json({ detail: 'Private video', needs_cookies: false }, 400),
    })
    renderApp('/download/tv/3')

    await openSeason('Season 1')
    const { field, row } = await inspectRow(label)

    expect(await row.findByRole('alert')).toHaveTextContent('Private video')
    // The URL stays put, so it can be corrected rather than retyped.
    expect(field).toHaveValue(URL)
    expect(row.queryByRole('button', { name: 'Download' })).not.toBeInTheDocument()
  })

  it('explains when the site wants cookies', async () => {
    mockSeries({
      'POST /api/inspect': () =>
        json({ detail: 'ERROR: Sign in to confirm your age', needs_cookies: true }, 400),
    })
    renderApp('/download/tv/3')

    await openSeason('Season 1')
    const { row } = await inspectRow(label)

    // The shared InspectCard's cookies explanation, not a bare error (§8).
    expect(await row.findByText('This video needs cookies.')).toBeInTheDocument()
  })
})

describe('a series page reached by "download again" (M9)', () => {
  const earlier: RequestRead = {
    id: 'req-1',
    media_type: 'tv',
    title: 'Some Show',
    year: null,
    numbering: 'standard',
    radarr_movie_id: null,
    sonarr_series_id: 3,
    options: { ...OPTIONS, quality: '1080p' } as RequestRead['options'],
    created_at: '2026-09-01T10:00:00',
    jobs: [{ id: 'job-1', url: URL, season: 1, sonarr_episode_id: 102 } as Job],
  }

  it('opens the episode and prefills it from a previous request', async () => {
    const fetchMock = mockSeries({ 'GET /api/requests/req-1': () => json(earlier) })
    renderApp('/download/tv/3?again=req-1&job=job-1')

    // The episode's season opens by itself; the others stay closed.
    const field = await screen.findByLabelText('Video URL for S01E02 · Episode 2 · 2024-03-08')
    await waitFor(() => expect(field).toHaveValue(URL))
    expect(screen.getByRole('button', { name: /^Season 1/ })).toHaveAttribute(
      'aria-expanded',
      'true',
    )
    expect(screen.getByRole('button', { name: /^Season 2/ })).toHaveAttribute(
      'aria-expanded',
      'false',
    )
    // The episode may be in Sonarr by now, so everything is listed.
    expect(
      screen.getByRole('checkbox', { name: 'Show episodes Sonarr already has' }),
    ).toBeChecked()
    // Only that row was filled in and inspected.
    expect(screen.getByLabelText('Video URL for S01E03 · Episode 3 · 2024-03-15')).toHaveValue('')
    await waitFor(() => expect(sentBodies(fetchMock, 'POST /api/inspect')).toEqual([{ url: URL }]))

    const row = within(field.closest('form')!.parentElement!)
    expect(await row.findByText(PATH)).toBeInTheDocument()
    fireEvent.click(row.getByRole('button', { name: 'Download' }))

    await waitFor(() =>
      expect(sentBodies(fetchMock, 'POST /api/requests')).toMatchObject([
        {
          media_type: 'tv',
          media: { sonarr_series_id: 3, title: 'Some Show' },
          items: [{ inspection_id: 7, episode: { sonarr_episode_id: 102, number: 2 } }],
          options: { ...OPTIONS, quality: '1080p' },
        },
      ]),
    )
  })
})
