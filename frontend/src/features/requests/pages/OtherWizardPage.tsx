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
import type { DownloadOptions, PreviewRequest } from '../types'

export default function OtherWizardPage() {
  const navigate = useNavigate()
  const [url, setUrl] = useState('')
  const [options, setOptions] = useState<DownloadOptions>({
    quality: 'best',
    container: 'mkv',
    fragments: 'auto',
    use_aria2c: 'auto',
    retries: 5,
  })

  const inspection = useMutation({ mutationFn: inspect })
  const inspectionId = inspection.data?.inspection_id

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
            <DownloadOptionsFields
              value={options}
              onChange={setOptions}
              heights={inspection.data.video_heights ?? []}
              estimatedSizes={inspection.data.estimated_sizes ?? {}}
            />

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
