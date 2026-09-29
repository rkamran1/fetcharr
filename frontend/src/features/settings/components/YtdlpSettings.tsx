import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { getSystemStatus, systemStatusQueryKey } from '@/features/system'

import { updateYtdlp } from '../api'

/** The yt-dlp version, and the button that upgrades it inside its own venv (§13.1). */
export default function YtdlpSettings() {
  const queryClient = useQueryClient()
  const status = useQuery({ queryKey: systemStatusQueryKey, queryFn: getSystemStatus })
  const update = useMutation({
    mutationFn: updateYtdlp,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: systemStatusQueryKey }),
  })

  const tools = status.data?.tools
  const result = update.data

  return (
    <Card role="region" aria-label="yt-dlp">
      <CardHeader>
        <CardTitle>
          <h2>yt-dlp</h2>
        </CardTitle>
        <CardDescription>
          yt-dlp lives in its own environment, so it can be updated without rebuilding the
          image. An update is lost when the container is recreated.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <dl className="flex flex-col gap-1 text-sm">
          <div className="flex gap-2">
            <dt className="text-muted-foreground w-40 shrink-0">Version</dt>
            <dd className="font-mono">{tools?.ytdlp ?? 'unknown'}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="text-muted-foreground w-40 shrink-0">Update on start</dt>
            <dd>{tools?.update_on_start ? 'on' : 'off'}</dd>
          </div>
        </dl>
        <div>
          <Button type="button" onClick={() => update.mutate()} disabled={update.isPending}>
            {update.isPending ? 'Updating…' : 'Update yt-dlp'}
          </Button>
        </div>
        {update.isError && (
          <p role="alert" className="text-destructive text-sm">
            {update.error.message}
          </p>
        )}
        {result && (
          <p role="status" className="text-sm">
            {result.old === result.new
              ? `Already up to date (${result.new ?? 'unknown'}).`
              : `Updated from ${result.old ?? 'unknown'} to ${result.new ?? 'unknown'}.`}
          </p>
        )}
      </CardContent>
    </Card>
  )
}
