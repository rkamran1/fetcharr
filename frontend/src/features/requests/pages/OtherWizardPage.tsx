import { useMutation, useQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { InspectCard, inspect } from '@/features/inspections'
import { formatBytes } from '@/lib/format'

import { createRequest, previewPath, previewQueryKey } from '../api'
import NativeSelect from '../components/NativeSelect'
import type { Container, DownloadOptions, PreviewRequest, Quality } from '../types'

const QUALITIES: Quality[] = ['144p', '240p', '360p', '480p', '720p', '1080p', '1440p', '2160p']
const FRAGMENTS = ['auto', '1', '2', '4', '8'] as const
const ARIA2C = ['auto', 'on', 'off'] as const

export default function OtherWizardPage() {
  const navigate = useNavigate()
  const [url, setUrl] = useState('')
  const [quality, setQuality] = useState<Quality>('best')
  const [container, setContainer] = useState<Container>('mkv')
  const [fragments, setFragments] = useState<(typeof FRAGMENTS)[number]>('auto')
  const [aria2c, setAria2c] = useState<(typeof ARIA2C)[number]>('auto')
  const [retries, setRetries] = useState(5)

  const inspection = useMutation({ mutationFn: inspect })
  const inspectionId = inspection.data?.inspection_id

  const options: DownloadOptions = {
    quality,
    container,
    fragments: fragments === 'auto' ? 'auto' : Number(fragments),
    use_aria2c: aria2c === 'auto' ? 'auto' : aria2c === 'on',
    retries,
  }

  const previewBody: PreviewRequest = {
    media_type: 'other',
    inspection_id: inspectionId ?? 0,
    options,
  }
  const preview = useQuery({
    queryKey: previewQueryKey(previewBody),
    queryFn: () => previewPath(previewBody),
    enabled: inspectionId !== undefined,
  })

  const download = useMutation({
    mutationFn: () =>
      createRequest({
        media_type: 'other',
        items: [{ inspection_id: inspectionId! }],
        options,
      }),
    onSuccess: () => navigate('/queue'),
  })

  // The heights this video really has (requirements §5 step 2d), coerced because a
  // height can arrive as a string, and de-duplicated.
  const heights = [...new Set((inspection.data?.video_heights ?? []).map(Number))].filter(
    (height) => Number.isFinite(height) && height > 0,
  )
  const tallest = heights.length > 0 ? Math.max(...heights) : 0

  // Roughly what a download will cost: a reported filesize, or the bitrate over the
  // running time, plus the audio track (§5 step 1). Always approximate, so say so.
  const sizes = inspection.data?.estimated_sizes ?? {}
  const sizeOf = (height: number): string =>
    sizes[String(height)] ? ` · ≈ ${formatBytes(sizes[String(height)])}` : ''

  // A quality is a ceiling ("at most this height"), so each one really downloads the
  // tallest format at or below it. Offer a step only when it picks a format nothing
  // else already picks, and name the height it will actually get, so a video with
  // unusual heights still shows real formats and real sizes.
  const picked = new Set<number>()
  const available: { value: Quality; label: string }[] = []
  for (const value of QUALITIES) {
    const ceiling = Number.parseInt(value)
    const effective = Math.max(0, ...heights.filter((height) => height <= ceiling))
    if (effective === 0 || picked.has(effective)) continue
    picked.add(effective)
    available.push({
      value,
      label: `${value}${effective === ceiling ? '' : ` → ${effective}p`}${sizeOf(effective)}`,
    })
  }
  available.reverse()

  // Name what "best" will actually download, so the collapsed control says something.
  const bestLabel =
    tallest > 0 ? `Best available (${tallest}p${sizeOf(tallest)})` : 'Best available'

  const submit = (event: FormEvent) => {
    event.preventDefault()
    inspection.mutate(url.trim())
  }

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Download Other</h1>
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
            <div className="flex flex-col gap-4 sm:flex-row">
              <div className="flex flex-col gap-2">
                <Label htmlFor="quality">Quality</Label>
                <NativeSelect
                  id="quality"
                  value={quality}
                  onChange={(e) => setQuality(e.target.value as Quality)}
                >
                  <option value="best">{bestLabel}</option>
                  {available.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </NativeSelect>
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="container">Container</Label>
                <NativeSelect
                  id="container"
                  value={container}
                  onChange={(e) => setContainer(e.target.value as Container)}
                >
                  <option value="mkv">mkv</option>
                  <option value="mp4">mp4</option>
                </NativeSelect>
              </div>
            </div>

            <details className="text-sm">
              <summary className="cursor-pointer">Advanced</summary>
              <div className="flex flex-col gap-4 pt-4 sm:flex-row">
                <div className="flex flex-col gap-2">
                  <Label htmlFor="fragments">Fragments</Label>
                  <NativeSelect
                    id="fragments"
                    value={fragments}
                    onChange={(e) => setFragments(e.target.value as (typeof FRAGMENTS)[number])}
                  >
                    {FRAGMENTS.map((value) => (
                      <option key={value} value={value}>
                        {value}
                      </option>
                    ))}
                  </NativeSelect>
                </div>
                <div className="flex flex-col gap-2">
                  <Label htmlFor="aria2c">aria2c</Label>
                  <NativeSelect
                    id="aria2c"
                    value={aria2c}
                    onChange={(e) => setAria2c(e.target.value as (typeof ARIA2C)[number])}
                  >
                    {ARIA2C.map((value) => (
                      <option key={value} value={value}>
                        {value}
                      </option>
                    ))}
                  </NativeSelect>
                </div>
                <div className="flex flex-col gap-2">
                  <Label htmlFor="retries">Retries</Label>
                  <Input
                    id="retries"
                    type="number"
                    min={0}
                    max={20}
                    className="w-24"
                    value={retries}
                    onChange={(e) => setRetries(Number(e.target.value))}
                  />
                </div>
              </div>
            </details>

            <p className="text-muted-foreground text-sm break-all">
              Saves to:{' '}
              {preview.isSuccess ? (
                <span className="font-mono">{preview.data.path}</span>
              ) : preview.isError ? (
                preview.error.message
              ) : (
                '…'
              )}
            </p>

            {download.isError && (
              <p role="alert" className="text-destructive text-sm">
                {download.error.message}
              </p>
            )}
            <Button
              type="button"
              className="self-start"
              onClick={() => download.mutate()}
              disabled={download.isPending}
            >
              Download
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
