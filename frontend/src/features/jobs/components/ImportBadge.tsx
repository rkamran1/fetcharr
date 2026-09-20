import { useMutation, useQueryClient } from '@tanstack/react-query'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'

import { jobsQueryKey, retryImport } from '../api'
import type { Job } from '../types'

/** ✅ / ⚠ / ❌ for the arr import, with the app's own reasons verbatim (§7.5, §12). */
export default function ImportBadge({ job }: { job: Job }) {
  // A TV job was sent to Sonarr; everything else that imports went to Radarr (§7.5).
  const app = job.media_type === 'tv' ? 'Sonarr' : 'Radarr'
  const queryClient = useQueryClient()
  const retry = useMutation({
    mutationFn: () => retryImport(job.id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: jobsQueryKey }),
  })

  if (job.import_status === 'n/a' || job.import_status === 'pending') return null

  const reasons = job.import_detail?.rejections ?? []
  const failure = job.import_detail?.error
  const hint = job.import_detail?.hint

  return (
    <div className="flex flex-col gap-2">
      {job.import_status === 'imported' && (
        <>
          <Badge variant="outline">✅ Imported</Badge>
          {job.imported_path && (
            <p className="text-muted-foreground text-xs break-all">{job.imported_path}</p>
          )}
        </>
      )}

      {job.import_status !== 'imported' && (
        <>
          <Badge variant="outline">
            {job.import_status === 'not_imported' ? '⚠ Not imported' : '❌ Import error'}
          </Badge>
          {reasons.length > 0 && (
            <ul aria-label={`${app}'s reasons`} className="text-muted-foreground text-xs">
              {reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          )}
          {failure && <p className="text-muted-foreground text-xs">{failure}</p>}
          {hint && <p className="text-muted-foreground text-xs">{hint}</p>}
          {job.completed_path && (
            <p className="text-muted-foreground text-xs break-all">
              Import manually: open {app} → Wanted → Manual Import → {job.completed_path}
            </p>
          )}
          <Button
            size="sm"
            className="self-start"
            onClick={() => retry.mutate()}
            disabled={retry.isPending}
          >
            Retry import
          </Button>
        </>
      )}
    </div>
  )
}
