import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { formatBytes } from '@/lib/format'

import { cancelJob, jobsQueryKey, retryJob } from '../api'
import type { Job, JobStatus } from '../types'
import ImportBadge from './ImportBadge'
import LogDrawer from './LogDrawer'

const PHASE_LABEL: Record<JobStatus, string> = {
  queued: 'Queued',
  starting: 'Starting',
  downloading: 'Downloading',
  postprocessing: 'Merging',
  transcoding: 'Transcoding',
  organizing: 'Moving',
  importing: 'Importing',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
}

// Everything before the job reaches a terminal state (requirements §6).
const RUNNING: JobStatus[] = [
  'queued',
  'starting',
  'downloading',
  'postprocessing',
  'transcoding',
  'organizing',
  'importing',
]

// Cancel is only possible before the organize step starts (requirements §6.1).
const CANCELLABLE: JobStatus[] = [
  'queued',
  'starting',
  'downloading',
  'postprocessing',
  'transcoding',
]

function formatEta(seconds: number): string {
  const minutes = Math.floor(seconds / 60)
  return `${minutes}:${String(Math.round(seconds % 60)).padStart(2, '0')}`
}

/** `S01E05 — Pilot`, or a daily episode's air date; empty for anything but TV (§12). */
function episodeLabel(job: Job): string {
  if (job.media_type !== 'tv') return ''
  const number =
    job.episode != null && job.season != null
      ? `S${String(job.season).padStart(2, '0')}E${String(job.episode).padStart(2, '0')}`
      : (job.air_date ?? '')
  return [number, job.episode_title].filter(Boolean).join(' — ')
}

export default function JobCard({ job }: { job: Job }) {
  const queryClient = useQueryClient()
  const [logOpen, setLogOpen] = useState(false)
  const invalidate = () => void queryClient.invalidateQueries({ queryKey: jobsQueryKey })
  const cancel = useMutation({
    mutationFn: () => cancelJob(job.id),
    onSuccess: invalidate,
  })
  const retry = useMutation({
    mutationFn: () => retryJob(job.id),
    onSuccess: invalidate,
  })

  const running = RUNNING.includes(job.status)
  const pct = job.progress_pct ?? 0
  const details = [
    job.speed_bps ? `${formatBytes(job.speed_bps)}/s` : null,
    job.eta_s != null ? `ETA ${formatEta(job.eta_s)}` : null,
    job.downloaded_bytes
      ? `${formatBytes(job.downloaded_bytes)}${job.total_bytes ? ` / ${formatBytes(job.total_bytes)}` : ''}`
      : null,
  ].filter(Boolean)

  return (
    <Card>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="min-w-0 flex-1 truncate font-medium">
            {episodeLabel(job) || (job.source_title ?? job.url)}
          </h2>
          <Badge variant="outline">{PHASE_LABEL[job.status]}</Badge>
        </div>
        {/* A TV card is named by its episode, so the video's own title goes below it. */}
        {episodeLabel(job) && job.source_title && (
          <p className="text-muted-foreground -mt-2 truncate text-xs">{job.source_title}</p>
        )}
        {running && (
          <div
            role="progressbar"
            aria-label="Progress"
            aria-valuenow={Math.round(pct)}
            aria-valuemin={0}
            aria-valuemax={100}
            className="bg-muted h-2 w-full overflow-hidden rounded-full"
          >
            <div className="bg-primary h-full" style={{ width: `${pct}%` }} />
          </div>
        )}
        {/* Speed and ETA belong to a running job; a finished one shows what it produced. */}
        {running && details.length > 0 && (
          <p className="text-muted-foreground text-sm">{details.join(' · ')}</p>
        )}
        {!running && job.file_size != null && (
          <p className="text-muted-foreground text-sm">{formatBytes(job.file_size)}</p>
        )}
        {job.error_message && (
          <p role="alert" className="text-destructive text-sm">
            {job.error_message}
          </p>
        )}
        {job.completed_path && (
          <p className="text-muted-foreground text-xs break-all">{job.completed_path}</p>
        )}
        <ImportBadge job={job} />
        <div className="flex flex-wrap gap-2">
          {CANCELLABLE.includes(job.status) && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => cancel.mutate()}
              disabled={cancel.isPending}
            >
              Cancel
            </Button>
          )}
          {job.status === 'failed' && (
            <Button size="sm" onClick={() => retry.mutate()} disabled={retry.isPending}>
              Retry
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={() => setLogOpen((open) => !open)}>
            Log
          </Button>
        </div>
        {logOpen && <LogDrawer jobId={job.id} />}
      </CardContent>
    </Card>
  )
}
