import { useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'

import { jobsQueryKey } from './api'
import type { Job, JobList, ProgressEvent, StateEvent } from './types'

function merge(queryClient: QueryClient, jobId: string, patch: Partial<Job>): void {
  let seen = false
  queryClient.setQueryData<JobList>(jobsQueryKey, (old) => {
    if (!old) return old
    const jobs = old.jobs.map((job) => {
      if (job.id !== jobId) return job
      seen = true
      return { ...job, ...patch }
    })
    return seen ? { jobs } : old
  })
  // A job we don't know yet (just queued, or the list is stale): ask for the list again.
  if (!seen) void queryClient.invalidateQueries({ queryKey: jobsQueryKey })
}

/** Keeps the jobs cache in step with the server's SSE stream (requirements §6). */
export function useJobEvents(): void {
  const queryClient = useQueryClient()

  useEffect(() => {
    const source = new EventSource('/api/events')

    const onProgress = (event: MessageEvent<string>) => {
      const { job_id: jobId, ...progress } = JSON.parse(event.data) as ProgressEvent
      merge(queryClient, jobId, progress)
    }
    const onState = (event: MessageEvent<string>) => {
      const { job_id: jobId, ...state } = JSON.parse(event.data) as StateEvent
      merge(queryClient, jobId, state)
    }
    // Every (re)connect refetches, so nothing missed while disconnected stays stale.
    const onOpen = () => void queryClient.invalidateQueries({ queryKey: jobsQueryKey })

    source.addEventListener('job.progress', onProgress)
    source.addEventListener('job.state', onState)
    source.addEventListener('open', onOpen)
    return () => source.close()
  }, [queryClient])
}
