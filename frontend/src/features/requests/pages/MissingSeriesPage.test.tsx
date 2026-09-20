import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { SonarrSeries } from '@/features/arr'
import { json, mockApi, renderApp } from '@/test/mockApi'

const base = {
  'GET /api/auth/me': () => json({ username: 'owner' }),
  'GET /healthz': () => json({ status: 'ok', version: '1.2.3' }),
}

/** Specials and season 1 complete; season 2 is ten episodes with one on disk (AC15). */
const SOME_SHOW: SonarrSeries = {
  id: 3,
  title: 'Some Show',
  series_type: 'standard',
  monitored: true,
  seasons: [
    { number: 0, episode_file_count: 2, episode_count: 2, total_episode_count: 2 },
    { number: 1, episode_file_count: 8, episode_count: 8, total_episode_count: 8 },
    // Four of the ten have aired, so only four can be found today.
    { number: 2, episode_file_count: 1, episode_count: 4, total_episode_count: 10 },
  ],
  poster: 'https://artworks.thetvdb.com/some-show.jpg',
}

/**
 * The Breaking Bad shape from the M6 review: added unmonitored, so Sonarr reports nothing
 * "wanted" while holding none of the episodes. Also has no poster (AC14).
 */
const OTHER_SHOW: SonarrSeries = {
  id: 7,
  title: 'Another Show',
  series_type: 'standard',
  monitored: false,
  seasons: [
    { number: 0, episode_file_count: 0, episode_count: 0, total_episode_count: 2 },
    { number: 1, episode_file_count: 3, episode_count: 0, total_episode_count: 4 },
  ],
  poster: null,
}

function mockSeries(overrides: Record<string, () => Response> = {}) {
  return mockApi({
    ...base,
    'GET /api/arr/sonarr/series?q=&missing=true': () =>
      json({ series: [SOME_SHOW, OTHER_SHOW] }),
    ...overrides,
  })
}

function shows() {
  return within(screen.getByRole('list', { name: 'Series missing episodes' })).getAllByRole(
    'listitem',
  )
}

/** What one card says, without the decorative poster (or its placeholder) in the way. */
function summary(item: HTMLElement): string {
  const series = within(item).getByRole('heading', { level: 2 })
  return `${series.textContent} — ${series.nextElementSibling?.textContent}`
}

describe('the missing series list (AC17)', () => {
  it('lists every series Sonarr is missing episodes from', async () => {
    mockSeries()
    renderApp('/download/tv')

    await screen.findByRole('list', { name: 'Series missing episodes' })

    // One card per series, saying how much work it is across how many seasons.
    expect(shows().map(summary)).toEqual([
      'Some Show — 9 missing across 1 season',
      'Another Show — 3 missing across 2 seasons',
    ])
    // Each opens that series' own page (AC18).
    expect(within(shows()[0]).getByRole('link')).toHaveAttribute('href', '/download/tv/3')
    expect(within(shows()[1]).getByRole('link')).toHaveAttribute('href', '/download/tv/7')
  })

  it('leaves out a series Sonarr has in full', async () => {
    mockSeries({
      'GET /api/arr/sonarr/series?q=&missing=true': () => json({ series: [SOME_SHOW] }),
    })
    renderApp('/download/tv')

    await screen.findByRole('list', { name: 'Series missing episodes' })

    // Specials and season 1 of "Some Show" are complete, so only season 2 counts.
    expect(shows()).toHaveLength(1)
    expect(summary(shows()[0])).toBe('Some Show — 9 missing across 1 season')
  })

  it('narrows the list by series title', async () => {
    const fetchMock = mockSeries({
      'GET /api/arr/sonarr/series?q=another&missing=true': () =>
        json({ series: [OTHER_SHOW] }),
    })
    renderApp('/download/tv')

    fireEvent.change(await screen.findByLabelText('Series missing episodes in Sonarr'), {
      target: { value: 'another' },
    })

    await waitFor(() => expect(shows()).toHaveLength(1))
    expect(screen.queryByText('Some Show')).not.toBeInTheDocument()
    expect(
      fetchMock.mock.calls.filter(([input]) => String(input).includes('q=another')),
    ).toHaveLength(1)
  })

  it('refreshes past the five-minute cache', async () => {
    let reads = 0
    mockSeries({
      'GET /api/arr/sonarr/series?q=&missing=true&refresh=true': () => {
        reads += 1
        return json({
          series: [
            SOME_SHOW,
            OTHER_SHOW,
            { ...OTHER_SHOW, id: 9, title: 'Newly Added', poster: null },
          ],
        })
      },
    })
    renderApp('/download/tv')

    await screen.findByRole('list', { name: 'Series missing episodes' })
    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }))

    // One request, answered into the same cache entry (M5c).
    expect(await screen.findByText('Newly Added')).toBeInTheDocument()
    expect(reads).toBe(1)
  })

  it("shows each series' poster, with a placeholder when it has none", async () => {
    mockSeries()
    renderApp('/download/tv')

    await screen.findByRole('list', { name: 'Series missing episodes' })

    // Decorative, exactly as the movie pickers treat Radarr's (AC14).
    const poster = within(shows()[0]).getByRole('presentation', { hidden: true })
    expect(poster).toHaveAttribute('src', SOME_SHOW.poster)
    expect(poster).toHaveAttribute('alt', '')
    expect(
      within(shows()[1]).queryByRole('presentation', { hidden: true }),
    ).not.toBeInTheDocument()
    expect(within(shows()[1]).getByText('?')).toBeInTheDocument()
  })

  it('says so when Sonarr is missing nothing, and points elsewhere for a series it lacks', async () => {
    mockSeries({
      'GET /api/arr/sonarr/series?q=&missing=true': () => json({ series: [] }),
    })
    renderApp('/download/tv')

    expect(
      await screen.findByText("Sonarr isn't missing episodes from anything that matches."),
    ).toBeInTheDocument()
    // §7.5's caveat: what arr doesn't know about goes through Other.
    expect(screen.getByRole('link', { name: 'Other' })).toHaveAttribute(
      'href',
      '/download/other',
    )
  })

  it('reports a Sonarr that cannot be reached', async () => {
    mockSeries({
      'GET /api/arr/sonarr/series?q=&missing=true': () =>
        json({ detail: 'Sonarr is not configured in Settings' }, 400),
    })
    renderApp('/download/tv')

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Sonarr is not configured in Settings',
    )
  })
})

describe('a series Sonarr is not monitoring (M6 review)', () => {
  it('lists it, and says why Sonarr will never fill it itself', async () => {
    mockSeries()
    renderApp('/download/tv')

    await screen.findByRole('list', { name: 'Series missing episodes' })

    // Sonarr reports nothing "wanted" for an unmonitored series, but the files aren't
    // there and this is exactly the series someone came to fill by hand.
    expect(summary(shows()[1])).toBe('Another Show — 3 missing across 2 seasons')
    expect(within(shows()[1]).getByText(/Not monitored in Sonarr/)).toBeInTheDocument()
    // The monitored one says nothing about monitoring.
    expect(within(shows()[0]).queryByText(/Not monitored/)).not.toBeInTheDocument()
  })
})
