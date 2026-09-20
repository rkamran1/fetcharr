import { useQuery } from '@tanstack/react-query'

import { jobsQueryKey, listJobs } from '../api'
import RequestGroup from '../components/RequestGroup'
import { useJobEvents } from '../events'
import type { Job } from '../types'

/** The jobs of one request together, newest request first (§12). */
function byRequest(jobs: Job[]): Job[][] {
  const groups = new Map<string, Job[]>()
  for (const job of jobs) {
    const group = groups.get(job.request_id)
    if (group) group.push(job)
    else groups.set(job.request_id, [job])
  }
  // Episode order inside a request, which is the order they are claimed in (§6.1).
  for (const group of groups.values()) {
    group.sort((a, b) => (a.episode ?? 0) - (b.episode ?? 0) || a.created_at.localeCompare(b.created_at))
  }
  return [...groups.values()]
}

export default function QueuePage() {
  const jobs = useQuery({ queryKey: jobsQueryKey, queryFn: listJobs })
  useJobEvents()

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Queue</h1>
      {jobs.isPending && <p className="text-muted-foreground text-sm">Loading…</p>}
      {jobs.isError && (
        <p role="alert" className="text-destructive text-sm">
          {jobs.error.message}
        </p>
      )}
      {jobs.isSuccess && jobs.data.jobs.length === 0 && (
        <p className="text-muted-foreground text-sm">Nothing downloading yet.</p>
      )}
      {jobs.data &&
        byRequest(jobs.data.jobs).map((group) => (
          <RequestGroup key={group[0].request_id} jobs={group} />
        ))}
    </div>
  )
}
