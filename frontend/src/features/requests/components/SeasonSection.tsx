import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { Card, CardContent } from '@/components/ui/card'
import { listSonarrEpisodes, sonarrEpisodesQueryKey, type SonarrSeason } from '@/features/arr'

import { usePrefill, type Prefill } from '../again'
import { missingInSeason, seasonLabel } from '../episodes'
import type { TvMedia } from '../types'
import EpisodeRow from './EpisodeRow'

type Props = {
  season: SonarrSeason
  media: TvMedia
  /** True to list the episodes Sonarr already has, so a file can be replaced (§7.5). */
  showAll: boolean
  /** "Download again" for an episode of this season: opens it on that episode. */
  prefill: Prefill | null
}

/**
 * One season of a series, collapsed until it is opened (§12). Its episodes are fetched on
 * the first open, so a series with ten seasons costs one request, not ten.
 */
export default function SeasonSection({ season, media, showAll, prefill }: Props) {
  const [open, setOpen] = useState(false)
  usePrefill(prefill, () => setOpen(true))
  const seriesId = media.sonarr_series_id!

  const episodes = useQuery({
    queryKey: sonarrEpisodesQueryKey(seriesId, season.number),
    queryFn: () => listSonarrEpisodes(seriesId, season.number),
    enabled: open,
  })

  const all = episodes.data?.episodes ?? []
  const listed = showAll ? all : all.filter((episode) => !episode.has_file)

  return (
    <Card>
      <CardContent className="flex flex-col gap-2">
        <button
          type="button"
          aria-expanded={open}
          className="flex items-center gap-3 text-left"
          onClick={() => setOpen((was) => !was)}
        >
          <span aria-hidden="true" className="text-muted-foreground">
            {open ? '▾' : '▸'}
          </span>
          <span className="flex-1 font-medium">{seasonLabel(season.number)}</span>
          <span className="text-muted-foreground text-sm">
            {missingInSeason(season)} missing
          </span>
        </button>

        {open && (
          <>
            {episodes.isPending && (
              <p role="status" className="text-muted-foreground text-sm">
                Loading episodes…
              </p>
            )}
            {episodes.isError && (
              <p role="alert" className="text-destructive text-sm">
                {episodes.error.message}
              </p>
            )}
            {episodes.isSuccess && listed.length === 0 && (
              <p className="text-muted-foreground text-sm">
                {showAll
                  ? 'Sonarr has no episodes in this season.'
                  : "Sonarr isn't missing anything in this season."}
              </p>
            )}
            {listed.map((episode) => (
              <EpisodeRow
                key={episode.id}
                episode={episode}
                media={media}
                prefill={prefill?.job.sonarr_episode_id === episode.id ? prefill : null}
              />
            ))}
          </>
        )}
      </CardContent>
    </Card>
  )
}
