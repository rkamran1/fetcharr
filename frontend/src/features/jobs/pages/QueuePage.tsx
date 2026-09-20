import { useQuery } from '@tanstack/react-query'

import { jobsQueryKey, listJobs } from '../api'
import JobCard from '../components/JobCard'
import { useJobEvents } from '../events'

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
      {jobs.data?.jobs.map((job) => <JobCard key={job.id} job={job} />)}
    </div>
  )
}
