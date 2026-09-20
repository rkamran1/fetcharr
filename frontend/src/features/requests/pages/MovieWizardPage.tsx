import { useMutation, useQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { InspectCard, inspect } from '@/features/inspections'

import { createRequest, previewPath, previewQueryKey } from '../api'
import DownloadOptionsFields from '../components/DownloadOptionsFields'
import RadarrMoviePicker from '../components/RadarrMoviePicker'
import type { CollisionPolicy, DownloadOptions, MovieMedia, PreviewRequest } from '../types'

// The words a video title carries that a Radarr search doesn't want (§5 step 2a).
const NOISE = /\b(official|full\s+movie|full\s+film|movie|film|trailer|hd|uhd|4k|remastered)\b/gi

/** The video title, cleaned into something worth searching Radarr for. */
function cleanTitle(title: string): string {
  return title
    .replace(/\[[^\]]*\]|\([^)]*\)/g, ' ')
    .replace(NOISE, ' ')
    .replace(/[|–—-]+\s*$/, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

export default function MovieWizardPage() {
  const navigate = useNavigate()
  const [url, setUrl] = useState('')
  const [media, setMedia] = useState<MovieMedia | null>(null)
  const [collision, setCollision] = useState<CollisionPolicy | null>(null)
  const [options, setOptions] = useState<DownloadOptions>({
    quality: 'best',
    container: 'mkv',
    fragments: 'auto',
    use_aria2c: 'auto',
    retries: 5,
  })

  const inspection = useMutation({ mutationFn: inspect })
  const inspectionId = inspection.data?.inspection_id

  const previewBody: PreviewRequest | null =
    inspectionId !== undefined && media
      ? { media_type: 'movie', media, inspection_id: inspectionId, options }
      : null
  const preview = useQuery({
    queryKey: previewQueryKey(previewBody ?? { media_type: 'other', inspection_id: 0, options }),
    queryFn: () => previewPath(previewBody!),
    enabled: previewBody !== null,
  })

  const download = useMutation({
    mutationFn: () =>
      createRequest({
        media_type: 'movie',
        media: media!,
        items: [{ inspection_id: inspectionId! }],
        options,
        // Nothing is in the way, so there is nothing to ask about (§7.3).
        collision_policy: preview.data?.exists ? collision! : 'keep_both',
      }),
    onSuccess: () => navigate('/queue'),
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setMedia(null)
    setCollision(null)
    inspection.mutate(url.trim())
  }

  const mustChoose = preview.data?.exists === true && collision === null

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Download Movie</h1>
      <form className="flex flex-col gap-2 sm:flex-row sm:items-end" onSubmit={submit}>
        <div className="flex flex-1 flex-col gap-2">
          <Label htmlFor="url">Video URL</Label>
          <Input
            id="url"
            type="url"
            inputMode="url"
            placeholder="https://www.youtube.com/watch?v=…"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            required
          />
        </div>
        <Button type="submit" disabled={inspection.isPending}>
          Inspect
        </Button>
      </form>

      {!inspection.isIdle && (
        <InspectCard
          isPending={inspection.isPending}
          error={inspection.error}
          data={inspection.data}
        />
      )}

      {inspection.isSuccess && (
        <Card>
          <CardContent className="flex flex-col gap-4">
            <RadarrMoviePicker
              key={inspection.data.inspection_id}
              initialQuery={cleanTitle(inspection.data.title ?? '')}
              value={media}
              onChange={(next) => {
                setMedia(next)
                setCollision(null)
              }}
            />

            <DownloadOptionsFields
              value={options}
              onChange={setOptions}
              heights={inspection.data.video_heights ?? []}
              estimatedSizes={inspection.data.estimated_sizes ?? {}}
            />

            <p className="text-muted-foreground text-sm break-all">
              Saves to:{' '}
              {!media ? (
                'pick the movie first'
              ) : preview.isSuccess ? (
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
                  An un-imported file for this already exists in completed/
                </legend>
                {(['replace', 'keep_both'] as const).map((policy) => (
                  <label key={policy} className="flex items-center gap-2 text-sm">
                    <input
                      type="radio"
                      name="collision"
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
              disabled={download.isPending || !media || mustChoose}
            >
              Download
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
