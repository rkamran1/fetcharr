import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { Fragment, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { ImportBadge, LogDrawer, type Job } from '@/features/jobs'
import {
  listRequests,
  requestListQueryKey,
  requestsQueryKey,
  type RequestRead,
} from '@/features/requests'

import HistoryFilters, { type Filters } from '../components/HistoryFilters'
import JobActions from '../components/JobActions'
import { useDebounced, useIsDesktop } from '../hooks'

const PER_PAGE = 25
/** One search per pause in typing, not one per key (§12). */
const SEARCH_DEBOUNCE_MS = 300

const TYPE_LABELS = { movie: 'Movie', tv: 'TV', other: 'Other' } as const

type Row = { request: RequestRead; job: Job }

/** What a row is called: the request, and for an episode which one. */
function title({ request, job }: Row): string {
  const name = request.title ?? job.source_title ?? job.url
  if (request.media_type !== 'tv') return name
  const code =
    job.episode !== null
      ? `S${String(job.season ?? 0).padStart(2, '0')}E${String(job.episode).padStart(2, '0')}`
      : job.air_date
  return [name, code, job.episode_title].filter(Boolean).join(' · ')
}

/** Naive UTC from the backend, shown as it is stored: `2026-09-21 14:05`. */
function when(timestamp: string): string {
  return timestamp.slice(0, 16).replace('T', ' ')
}

function Status({ job }: { job: Job }) {
  return (
    <span className="flex flex-col gap-0.5">
      <span>{job.status}</span>
      {job.error_message && (
        <span className="text-muted-foreground text-xs break-words">{job.error_message}</span>
      )}
    </span>
  )
}

/** A searchable, filterable record of every download, with its follow-up actions (§12). */
export default function HistoryPage() {
  const queryClient = useQueryClient()
  const desktop = useIsDesktop()
  const [filters, setFilters] = useState<Filters>({})
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [openLog, setOpenLog] = useState<string | null>(null)
  const q = useDebounced(search.trim(), SEARCH_DEBOUNCE_MS)

  const query = { ...filters, q: q || undefined, page, per_page: PER_PAGE }
  const history = useQuery({
    queryKey: requestListQueryKey(query),
    queryFn: () => listRequests(query),
    placeholderData: keepPreviousData,
  })

  const refresh = () => void queryClient.invalidateQueries({ queryKey: requestsQueryKey })
  const rows: Row[] = (history.data?.items ?? []).flatMap((request) =>
    request.jobs.map((job) => ({ request, job })),
  )
  const pages = Math.max(1, Math.ceil((history.data?.total ?? 0) / PER_PAGE))

  const actions = (row: Row) => (
    <JobActions
      request={row.request}
      job={row.job}
      logOpen={openLog === row.job.id}
      onToggleLog={() => setOpenLog(openLog === row.job.id ? null : row.job.id)}
      onChanged={refresh}
    />
  )
  const importBadge = (row: Row) =>
    row.job.import_status === 'n/a' ? (
      <span className="text-muted-foreground">—</span>
    ) : (
      <ImportBadge job={row.job} onRetried={refresh} />
    )

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">History</h1>

      <Input
        type="search"
        aria-label="Search history"
        placeholder="Search titles"
        value={search}
        onChange={(event) => {
          setSearch(event.target.value)
          setPage(1)
        }}
      />
      <HistoryFilters
        value={filters}
        onChange={(next) => {
          setFilters(next)
          setPage(1)
        }}
      />

      {history.isError && (
        <p role="alert" className="text-destructive text-sm">
          {history.error.message}
        </p>
      )}
      {history.isPending && <p className="text-muted-foreground text-sm">Loading…</p>}
      {history.isSuccess && rows.length === 0 && (
        <p className="text-muted-foreground text-sm">Nothing downloaded matches.</p>
      )}

      {rows.length > 0 &&
        (desktop ? (
          <table className="w-full text-left text-sm">
            <thead className="text-muted-foreground border-b text-xs">
              <tr>
                <th className="py-2 pr-3 font-medium">Title</th>
                <th className="py-2 pr-3 font-medium">Type</th>
                <th className="py-2 pr-3 font-medium">Site</th>
                <th className="py-2 pr-3 font-medium">Date</th>
                <th className="py-2 pr-3 font-medium">Status</th>
                <th className="py-2 pr-3 font-medium">Import</th>
                <th className="py-2 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <Fragment key={row.job.id}>
                  <tr className="border-b align-top">
                    <td className="py-2 pr-3">
                      <span className="font-medium">{title(row)}</span>
                      {row.job.completed_path && (
                        <span className="text-muted-foreground block text-xs break-all">
                          {row.job.completed_path}
                        </span>
                      )}
                    </td>
                    <td className="py-2 pr-3">{TYPE_LABELS[row.request.media_type]}</td>
                    <td className="py-2 pr-3">{row.job.site_key ?? '—'}</td>
                    <td className="py-2 pr-3 whitespace-nowrap">{when(row.request.created_at)}</td>
                    <td className="py-2 pr-3">
                      <Status job={row.job} />
                    </td>
                    <td className="py-2 pr-3">{importBadge(row)}</td>
                    <td className="py-2">{actions(row)}</td>
                  </tr>
                  {openLog === row.job.id && (
                    <tr>
                      <td colSpan={7} className="py-2">
                        <LogDrawer jobId={row.job.id} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        ) : (
          <ul aria-label="History" className="flex flex-col gap-3">
            {rows.map((row) => (
              <li key={row.job.id}>
                <Card>
                  <CardContent className="flex flex-col gap-2">
                    <p className="font-medium break-words">{title(row)}</p>
                    <p className="text-muted-foreground text-xs">
                      {[
                        TYPE_LABELS[row.request.media_type],
                        row.job.site_key,
                        when(row.request.created_at),
                      ]
                        .filter(Boolean)
                        .join(' · ')}
                    </p>
                    <Status job={row.job} />
                    {row.job.completed_path && (
                      <p className="text-muted-foreground text-xs break-all">
                        {row.job.completed_path}
                      </p>
                    )}
                    {importBadge(row)}
                    {actions(row)}
                    {openLog === row.job.id && <LogDrawer jobId={row.job.id} />}
                  </CardContent>
                </Card>
              </li>
            ))}
          </ul>
        ))}

      {pages > 1 && (
        <nav aria-label="Pages" className="flex items-center gap-3 text-sm">
          <Button
            size="sm"
            variant="outline"
            onClick={() => setPage(page - 1)}
            disabled={page <= 1}
          >
            Previous
          </Button>
          <span>
            Page {page} of {pages}
          </span>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setPage(page + 1)}
            disabled={page >= pages}
          >
            Next
          </Button>
        </nav>
      )}
    </div>
  )
}
