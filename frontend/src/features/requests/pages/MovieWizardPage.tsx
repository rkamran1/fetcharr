import { PresetSelector, useDefaultPreset } from '@/features/presets'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { InspectCard, inspect } from '@/features/inspections'
import { CookiesChip } from '@/features/sites'

import { usePrefill, useDownloadAgain, useIsDownloadAgain } from '../again'
import { createRequest, previewPath, previewQueryKey } from '../api'
import DownloadOptionsFields from '../components/DownloadOptionsFields'
import MissingMoviePicker from '../components/MissingMoviePicker'
import RadarrMoviePicker from '../components/RadarrMoviePicker'
import { DEFAULT_OPTIONS } from '../types'
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

/** The two ways into the wizard: URL first (M5b), or the movie first (M5c). */
type Tab = 'url' | 'missing'

const TABS: { id: Tab; label: string }[] = [
  { id: 'url', label: 'Paste a URL' },
  { id: 'missing', label: 'Missing in Radarr' },
]

export default function MovieWizardPage() {
  const navigate = useNavigate()
  const [tab, setTab] = useState<Tab>('url')
  const [url, setUrl] = useState('')
  const [media, setMedia] = useState<MovieMedia | null>(null)
  const [collision, setCollision] = useState<CollisionPolicy | null>(null)
  const [options, setOptions] = useState<DownloadOptions>(DEFAULT_OPTIONS)
  const [useCookies, setUseCookies] = useState(true)

  const inspection = useMutation({ mutationFn: inspect })
  const inspectionId = inspection.data?.inspection_id

  // "Download again" from History: the same movie and URL, with the old options.
  useDefaultPreset('movie', setOptions, !useIsDownloadAgain())
  usePrefill(useDownloadAgain(), ({ request, job, options }) => {
    setTab('url')
    setMedia(
      request.title
        ? { radarr_movie_id: request.radarr_movie_id, title: request.title, year: request.year }
        : null,
    )
    setCollision(null)
    setUrl(job.url)
    setOptions(options)
    inspection.mutate(job.url)
  })

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
        use_cookies: useCookies,
      }),
    onSuccess: () => navigate('/queue'),
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    // The URL tab picks its movie after inspecting; the missing tab already has one.
    if (tab === 'url') setMedia(null)
    setCollision(null)
    setUseCookies(true)
    inspection.mutate(url.trim())
  }

  /** Nothing half-filled survives a tab change, so a URL can only meet a movie picked here. */
  const switchTo = (next: Tab) => {
    setTab(next)
    setUrl('')
    setMedia(null)
    setCollision(null)
    inspection.reset()
  }

  const mustChoose = preview.data?.exists === true && collision === null
  // On the missing tab the URL is only asked for once a movie has been chosen.
  const askForUrl = tab === 'url' || media !== null

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Download Movie</h1>

      <div role="tablist" aria-label="How to start" className="flex gap-2">
        {TABS.map(({ id, label }) => (
          <Button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            variant={tab === id ? 'default' : 'outline'}
            size="sm"
            onClick={() => switchTo(id)}
          >
            {label}
          </Button>
        ))}
      </div>

      {tab === 'missing' && (
        <Card>
          <CardContent>
            <MissingMoviePicker
              value={media}
              onChange={(next) => {
                setMedia(next)
                setCollision(null)
                // Un-picking takes the URL form away with it, so nothing is left dangling.
                if (next === null) {
                  setUrl('')
                  inspection.reset()
                }
              }}
            />
          </CardContent>
        </Card>
      )}

      {askForUrl && (
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
      )}

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
            {tab === 'url' && (
              <RadarrMoviePicker
                key={inspection.data.inspection_id}
                initialQuery={cleanTitle(inspection.data.title ?? '')}
                value={media}
                onChange={(next) => {
                  setMedia(next)
                  setCollision(null)
                }}
              />
            )}

            <PresetSelector mediaType="movie" options={options} onApply={setOptions} />
            <DownloadOptionsFields
              value={options}
              onChange={setOptions}
              heights={inspection.data.video_heights ?? []}
              estimatedSizes={inspection.data.estimated_sizes ?? {}}
              subtitles={inspection.data.subtitles ?? {}}
              automaticCaptions={inspection.data.automatic_captions ?? {}}
              audioTracks={inspection.data.audio_tracks ?? []}
              hasHdr={inspection.data.has_hdr ?? false}
            />
            <CookiesChip
              siteKey={inspection.data.site_key ?? null}
              useCookies={useCookies}
              onChange={setUseCookies}
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
