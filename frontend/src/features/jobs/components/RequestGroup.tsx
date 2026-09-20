import type { Job } from '../types'
import JobCard from './JobCard'

const DONE = new Set(['completed', 'failed', 'cancelled'])

/** "Some Show · Season 1", or the request's own title for a movie (§12). */
function groupTitle(jobs: Job[]): string {
  const [first] = jobs
  const title = first.request_title ?? first.source_title ?? first.url
  if (first.media_type !== 'tv') return title
  const seasons = [...new Set(jobs.map((job) => job.season))].filter((season) => season !== null)
  if (seasons.length !== 1) return title
  return `${title} · ${seasons[0] === 0 ? 'Specials' : `Season ${seasons[0]}`}`
}

/**
 * One request and its jobs (§12). A TV request is several episodes under one heading with a
 * done count; a movie or an `other` download is one job, so the heading is just its name.
 */
export default function RequestGroup({ jobs }: { jobs: Job[] }) {
  const done = jobs.filter((job) => DONE.has(job.status)).length

  return (
    <section aria-label={groupTitle(jobs)} className="flex flex-col gap-2">
      {jobs.length > 1 && (
        <h2 className="flex flex-wrap items-baseline gap-2 text-sm font-medium">
          {groupTitle(jobs)}
          <span className="text-muted-foreground font-normal">
            {done}/{jobs.length}
          </span>
        </h2>
      )}
      {jobs.map((job) => (
        <JobCard key={job.id} job={job} />
      ))}
    </section>
  )
}
