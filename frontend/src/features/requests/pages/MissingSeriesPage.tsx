import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { searchSonarrSeries, sonarrSeriesQueryKey, type SonarrSeries } from '@/features/arr'

import Poster from '../components/Poster'
import { missingEpisodes, missingInSeason } from '../episodes'

/** "80 missing across 6 seasons", so a card says how much work it is (§12). */
function gap(series: SonarrSeries): string {
  const seasons = series.seasons.filter((season) => missingInSeason(season) > 0).length
  const episodes = missingEpisodes(series)
  return `${episodes} missing across ${seasons} ${seasons === 1 ? 'season' : 'seasons'}`
}

/**
 * The way into a TV download: the series Sonarr is short of episodes for (§5 step 2b, §12).
 * Pick one and its own page breaks it down by season.
 */
export default function MissingSeriesPage() {
  const [query, setQuery] = useState('')
  const queryClient = useQueryClient()
  const key = sonarrSeriesQueryKey(query.trim(), true)

  const series = useQuery({
    queryKey: key,
    queryFn: () => searchSonarrSeries(query.trim(), true),
  })

  // fetcharr caches Sonarr's series for five minutes, so a series just added there needs a
  // way in without waiting it out. The answer lands in the same cache entry (M5c).
  const refresh = useMutation({
    mutationFn: () => searchSonarrSeries(query.trim(), true, true),
    onSuccess: (data) => queryClient.setQueryData(key, data),
  })

  const shows = series.data?.series ?? []

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Download TV Show</h1>

      <div className="flex flex-col gap-2">
        <Label htmlFor="series-search">Series missing episodes in Sonarr</Label>
        <div className="flex gap-2">
          <Input
            id="series-search"
            className="flex-1"
            value={query}
            placeholder="Search the series Sonarr is missing episodes from"
            onChange={(e) => setQuery(e.target.value)}
          />
          <Button
            type="button"
            variant="outline"
            onClick={() => refresh.mutate()}
            disabled={refresh.isPending}
          >
            {refresh.isPending ? 'Refreshing…' : 'Refresh'}
          </Button>
        </div>
        <p className="text-muted-foreground text-xs">
          Sonarr&apos;s library is cached for five minutes. Refresh after adding a series
          there. A series Sonarr doesn&apos;t have at all goes through{' '}
          <Link to="/download/other" className="underline">
            Other
          </Link>{' '}
          instead.
        </p>
      </div>

      {(series.isError || refresh.isError) && (
        <p role="alert" className="text-destructive text-sm">
          {(series.error ?? refresh.error)?.message}
        </p>
      )}

      {series.isPending && <p className="text-muted-foreground text-sm">Loading…</p>}

      {series.isSuccess &&
        (shows.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            Sonarr isn&apos;t missing episodes from anything that matches.
          </p>
        ) : (
          <ul aria-label="Series missing episodes" className="flex flex-col gap-3">
            {shows.map((show) => (
              <li key={show.id}>
                <Link to={`/download/tv/${show.id}`} className="rounded-xl focus-visible:ring-2">
                  <Card className="hover:border-primary transition-colors">
                    <CardContent className="flex items-center gap-4">
                      <Poster url={show.poster} className="w-16" />
                      <div className="flex min-w-0 flex-col gap-1">
                        <h2 className="truncate font-medium">{show.title}</h2>
                        <p className="text-muted-foreground text-sm">{gap(show)}</p>
                        {!show.monitored && (
                          <p className="text-muted-foreground text-xs">
                            Not monitored in Sonarr, so Sonarr won&apos;t look for these itself.
                          </p>
                        )}
                      </div>
                    </CardContent>
                  </Card>
                </Link>
              </li>
            ))}
          </ul>
        ))}
    </div>
  )
}
