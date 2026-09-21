import { useMutation } from '@tanstack/react-query'
import { useId } from 'react'
import { useNavigate } from 'react-router'

import { Button } from '@/components/ui/button'
import { deleteJobFile, retryJob, type Job } from '@/features/jobs'
import { againPath, type RequestRead } from '@/features/requests'

const FINISHED = ['completed', 'failed', 'cancelled']
const MANAGED = 'Managed by Radarr/Sonarr now'

type Props = {
  request: RequestRead
  job: Job
  logOpen: boolean
  onToggleLog: () => void
  /** After an action changed the job, so the page refetches. */
  onChanged: () => void
}

/** A History row's actions (§12); Retry import sits in the import badge beside them. */
export default function JobActions({ request, job, logOpen, onToggleLog, onChanged }: Props) {
  const navigate = useNavigate()
  const managedId = useId()
  const retry = useMutation({
    mutationFn: () => retryJob(job.id),
    onSuccess: onChanged,
  })
  const remove = useMutation({
    mutationFn: () => deleteJobFile(job.id),
    onSuccess: onChanged,
  })

  const imported = job.import_status === 'imported'
  // A file fetcharr still has: moved into completed/, not deleted since, and not running.
  const hasFile =
    FINISHED.includes(job.status) && job.completed_path !== null && job.file_deleted_at === null
  const error = retry.error ?? remove.error

  const deleteFile = () => {
    if (window.confirm(`Delete ${job.completed_path} and its subtitles?`)) remove.mutate()
  }

  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap gap-2">
        {job.status === 'failed' && (
          <Button size="sm" onClick={() => retry.mutate()} disabled={retry.isPending}>
            Retry download
          </Button>
        )}
        <Button size="sm" variant="outline" aria-expanded={logOpen} onClick={onToggleLog}>
          {logOpen ? 'Hide log' : 'Open log'}
        </Button>
        <Button size="sm" variant="outline" onClick={() => navigate(againPath(request, job))}>
          Download again
        </Button>
        {hasFile && (
          <span title={imported ? MANAGED : undefined}>
            <Button
              size="sm"
              variant="outline"
              onClick={deleteFile}
              disabled={imported || remove.isPending}
              aria-describedby={imported ? managedId : undefined}
            >
              Delete file
            </Button>
          </span>
        )}
      </div>
      {/* Visible, because a phone has no hover to show the tooltip. */}
      {hasFile && imported && (
        <p id={managedId} className="text-muted-foreground text-xs">
          {MANAGED}
        </p>
      )}
      {job.file_deleted_at && <p className="text-muted-foreground text-xs">File deleted</p>}
      {error && (
        <p role="alert" className="text-destructive text-xs">
          {error.message}
        </p>
      )}
    </div>
  )
}
