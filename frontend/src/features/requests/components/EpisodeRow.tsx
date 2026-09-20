import { useMutation, useQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import type { SonarrEpisode } from '@/features/arr'
import { InspectCard, inspect } from '@/features/inspections'

import { createRequest, previewPath, previewQueryKey } from '../api'
import { episodeLabel } from '../episodes'
import type { CollisionPolicy, DownloadOptions, EpisodeRef, PreviewRequest, TvMedia } from '../types'
import DownloadOptionsFields from './DownloadOptionsFields'

type Props = {
  episode: SonarrEpisode
  media: TvMedia
}

const DEFAULT_OPTIONS: DownloadOptions = {
  quality: 'best',
  container: 'mkv',
  fragments: 'auto',
  use_aria2c: 'auto',
  retries: 5,
}

function episodeRef(episode: SonarrEpisode): EpisodeRef {
  return {
    season: episode.season,
    number: episode.number,
    sonarr_episode_id: episode.id,
    title: episode.title,
    air_date: episode.air_date,
  }
}

/**
 * One episode of an opened season: a URL, its own Inspect, and then the options that this
 * video really has before Download queues exactly this episode (§5 steps 1 and 2d, §7.3).
 *
 * Everything here belongs to one link. Two rows in the same season are inspected
 * separately and can be downloaded at different qualities.
 */
export default function EpisodeRow({ episode, media }: Props) {
  const [url, setUrl] = useState('')
  const [options, setOptions] = useState<DownloadOptions>(DEFAULT_OPTIONS)
  const [collision, setCollision] = useState<CollisionPolicy | null>(null)
  const [queued, setQueued] = useState(false)

  const label = episodeLabel(episode, media.numbering === 'daily')
  const inspection = useMutation({ mutationFn: inspect })
  const inspectionId = inspection.data?.inspection_id

  const previewBody: PreviewRequest | null =
    inspectionId === undefined
      ? null
      : {
          media_type: 'tv',
          media,
          inspection_id: inspectionId,
          episode: episodeRef(episode),
          options,
        }
  const preview = useQuery({
    queryKey: previewQueryKey(previewBody ?? { media_type: 'other', inspection_id: 0, options }),
    queryFn: () => previewPath(previewBody!),
    enabled: previewBody !== null,
  })

  const download = useMutation({
    mutationFn: () =>
      createRequest({
        media_type: 'tv',
        media,
        items: [{ inspection_id: inspectionId!, episode: episodeRef(episode) }],
        options,
        // Nothing is in the way, so there is nothing to ask about (§7.3).
        collision_policy: preview.data?.exists ? collision! : 'keep_both',
      }),
    onSuccess: () => setQueued(true),
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setCollision(null)
    inspection.mutate(url.trim())
  }

  const mustChoose = preview.data?.exists === true && collision === null

  return (
    <div className="flex flex-col gap-2 border-t py-3 first:border-t-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-sm font-medium">{label}</span>
        {episode.has_file && (
          <Badge variant="outline">Sonarr has {episode.quality ?? 'a file'}</Badge>
        )}
        {queued && <Badge variant="outline">Queued</Badge>}
      </div>

      {queued ? (
        <p role="status" className="text-muted-foreground text-xs break-all">
          Queued. {preview.data?.path}
        </p>
      ) : (
        <form className="flex flex-col gap-2 sm:flex-row sm:items-center" onSubmit={submit}>
          <Input
            type="url"
            inputMode="url"
            aria-label={`Video URL for ${label}`}
            placeholder="https://www.youtube.com/watch?v=…"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            required
          />
          <Button type="submit" variant="outline" disabled={inspection.isPending}>
            Inspect
          </Button>
        </form>
      )}

      {!queued && !inspection.isIdle && (
        <InspectCard
          isPending={inspection.isPending}
          error={inspection.error}
          data={inspection.data}
        />
      )}

      {!queued && inspection.isSuccess && (
        <div className="flex flex-col gap-3">
          {/* Seeded from this video's own formats, so the choices are real (§5 step 2d). */}
          <DownloadOptionsFields
            value={options}
            onChange={setOptions}
            heights={inspection.data.video_heights ?? []}
            estimatedSizes={inspection.data.estimated_sizes ?? {}}
          />

          <p className="text-muted-foreground text-xs break-all">
            Saves to:{' '}
            {preview.isSuccess ? (
              <span className="font-mono">{preview.data.path}</span>
            ) : preview.isError ? (
              preview.error.message
            ) : (
              '…'
            )}
          </p>

          {preview.data?.exists && (
            <fieldset className="flex flex-col gap-2">
              <legend className="text-sm">
                An un-imported file for this episode already exists in completed/
              </legend>
              {(['replace', 'keep_both'] as const).map((policy) => (
                <label key={policy} className="flex items-center gap-2 text-sm">
                  <input
                    type="radio"
                    name={`collision-${episode.id}`}
                    value={policy}
                    checked={collision === policy}
                    onChange={() => setCollision(policy)}
                  />
                  {policy === 'replace' ? 'Replace' : 'Keep both'}
                </label>
              ))}
            </fieldset>
          )}

          {download.isError && (
            <p role="alert" className="text-destructive text-sm">
              {download.error.message}
            </p>
          )}

          <Button
            type="button"
            className="self-start"
            onClick={() => download.mutate()}
            disabled={download.isPending || mustChoose}
          >
            Download
          </Button>
        </div>
      )}
    </div>
  )
}
