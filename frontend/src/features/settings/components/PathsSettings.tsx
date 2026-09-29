import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { getSystemStatus, systemStatusQueryKey } from '@/features/system'

/** Paths and concurrency, read-only: both come from the environment (§11, §13.4). */
export default function PathsSettings() {
  const status = useQuery({ queryKey: systemStatusQueryKey, queryFn: getSystemStatus })
  const paths = status.data?.paths
  const concurrency = status.data?.concurrency

  return (
    <Card role="region" aria-label="Paths and concurrency">
      <CardHeader>
        <CardTitle>
          <h2>Paths and concurrency</h2>
        </CardTitle>
        <CardDescription>
          Set in the container's environment, so they change in your compose file, not here.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-col gap-1 text-sm">
          <p role="status">
            {paths === undefined
              ? 'Checking the download folders…'
              : paths.ok
                ? 'Every download folder is writable, on one volume.'
                : 'Some download folders cannot be used.'}
          </p>
          {paths?.checks.map((check) => (
            <p key={check.path} className="text-muted-foreground font-mono break-all">
              {check.ok ? '✓' : '✗'} {check.path}
              {check.error ? ` — ${check.error}` : ''}
            </p>
          ))}
          {paths && !paths.same_filesystem && (
            <p role="alert" className="text-destructive">
              completed/ and incomplete/ are on different volumes, so every finished download
              is copied instead of renamed.
            </p>
          )}
        </div>
        <dl className="flex flex-col gap-1 text-sm">
          <div className="flex gap-2">
            <dt className="text-muted-foreground w-48 shrink-0">Concurrent downloads</dt>
            <dd>{concurrency?.downloads ?? '…'}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="text-muted-foreground w-48 shrink-0">Concurrent transcodes</dt>
            <dd>{concurrency?.transcodes ?? '…'}</dd>
          </div>
        </dl>
        <p className="text-sm">
          <Link className="underline" to="/status">
            Full status report
          </Link>
        </p>
      </CardContent>
    </Card>
  )
}
