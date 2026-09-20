import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router'

import { searchSonarrSeries, sonarrSeriesQueryKey } from '@/features/arr'

import Poster from '../components/Poster'
import SeasonSection from '../components/SeasonSection'
import { missingInSeason } from '../episodes'
import type { TvMedia } from '../types'

/**
 * One series and its gaps (§5 step 2b, §12): a collapsible section per season, and inside
 * each the episodes to fill. Quality and the rest belong to each link, not to this page,
 * because only an inspected video knows which formats it really has (AC20).
 */
export default function SeriesPage() {
  const params = useParams()
  const seriesId = Number(params.seriesId)
  const [showAll, setShowAll] = useState(false)

  // The series list is cached both sides, so naming this series costs one request at most.
  const series = useQuery({
    queryKey: sonarrSeriesQueryKey('', false),
    queryFn: () => searchSonarrSeries(''),
  })
  const show = series.data?.series.find((candidate) => candidate.id === seriesId)

  const media: TvMedia | null = show
    ? { sonarr_series_id: show.id, title: show.title, numbering: show.series_type }
    : null
  // A season Sonarr has in full is not something to fill, unless everything is on show.
  const seasons = (show?.seasons ?? []).filter(
    (season) => showAll || missingInSeason(season) > 0,
  )

  return (
    <div className="flex flex-col gap-4">
      <Link to="/download/tv" className="text-muted-foreground text-sm underline">
        ← All missing series
      </Link>

      <div className="flex items-center gap-4">
        <Poster url={show?.poster ?? null} className="w-16" />
        <div className="flex min-w-0 flex-col">
          <h1 className="truncate text-xl font-semibold">{show?.title ?? 'Series'}</h1>
          {show && !show.monitored && (
            <p className="text-muted-foreground text-sm">
              Not monitored in Sonarr, so Sonarr won&apos;t look for these itself.
            </p>
          )}
        </div>
      </div>

      {series.isError && (
        <p role="alert" className="text-destructive text-sm">
          {series.error.message}
        </p>
      )}
      {series.isPending && <p className="text-muted-foreground text-sm">Loading…</p>}

      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />
        Show episodes Sonarr already has
      </label>

      {series.isSuccess && !show && (
        <p className="text-muted-foreground text-sm">Sonarr doesn&apos;t have that series.</p>
      )}

      {media && seasons.length > 0 && (
        <ul aria-label="Seasons" className="flex flex-col gap-2">
          {seasons.map((season) => (
            <li key={season.number}>
              <SeasonSection season={season} media={media} showAll={showAll} />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
