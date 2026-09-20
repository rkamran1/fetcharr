import { useQuery } from '@tanstack/react-query'

import { getJobLog, jobLogQueryKey } from '../api'

/** The job's log lines, fetched when the drawer opens. */
export default function LogDrawer({ jobId }: { jobId: string }) {
  const log = useQuery({ queryKey: jobLogQueryKey(jobId), queryFn: () => getJobLog(jobId) })

  return (
    <section aria-label="Log" className="bg-muted max-h-64 overflow-auto rounded-md p-3">
      {log.isPending && <p className="text-muted-foreground text-sm">Loading…</p>}
      {log.isError && (
        <p role="alert" className="text-destructive text-sm">
          {log.error.message}
        </p>
      )}
      {log.isSuccess &&
        (log.data.lines.length === 0 ? (
          <p className="text-muted-foreground text-sm">No log lines yet.</p>
        ) : (
          <pre className="text-xs whitespace-pre-wrap">
            {log.data.lines.map((line) => line.line).join('\n')}
          </pre>
        ))}
    </section>
  )
}
