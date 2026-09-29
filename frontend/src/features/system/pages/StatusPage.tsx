import { useQuery } from '@tanstack/react-query'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

import { getSystemStatus, systemStatusQueryKey } from '../api'
import type { ArrStatus } from '../types'

function Section({ name, children }: { name: string; children: React.ReactNode }) {
  return (
    <Card role="region" aria-label={name}>
      <CardHeader>
        <CardTitle>
          <h2>{name}</h2>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="flex flex-col gap-1 text-sm">{children}</dl>
      </CardContent>
    </Card>
  )
}

function Row({ name, value }: { name: string; value: React.ReactNode }) {
  return (
    <div className="flex flex-col sm:flex-row sm:gap-2">
      <dt className="text-muted-foreground w-48 shrink-0">{name}</dt>
      <dd className="break-all">{value}</dd>
    </div>
  )
}

function arrLine(arr: ArrStatus): string {
  if (!arr.configured) return 'not configured'
  return arr.ok ? `reachable, version ${arr.version ?? 'unknown'}` : `unreachable — ${arr.error}`
}

function megabytes(bytes: number | null): string {
  return bytes === null ? 'unknown' : `${(bytes / 1_000_000).toFixed(1)} MB`
}

/** The whole self-test in one page (§11), refreshed on demand. */
export default function StatusPage() {
  const status = useQuery({ queryKey: systemStatusQueryKey, queryFn: getSystemStatus })
  const data = status.data

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between gap-4">
        <h1>Status</h1>
        <Button
          type="button"
          variant="outline"
          onClick={() => status.refetch()}
          disabled={status.isFetching}
        >
          {status.isFetching ? 'Checking…' : 'Re-run checks'}
        </Button>
      </div>
      {status.isError && (
        <p role="alert" className="text-destructive text-sm">
          {status.error.message}
        </p>
      )}
      {data && (
        <>
          <Section name="Versions">
            <Row name="fetcharr" value={data.version} />
            <Row name="yt-dlp" value={data.tools.ytdlp ?? 'not installed'} />
            <Row name="ffmpeg" value={data.tools.ffmpeg ?? 'not installed'} />
            <Row name="deno" value={data.tools.deno ?? 'not installed'} />
            <Row name="JS runtime" value={data.tools.js_runtime ?? 'none detected'} />
            <Row name="aria2c" value={data.tools.aria2c ? 'available' : 'not installed'} />
            <Row name="Update yt-dlp on start" value={data.tools.update_on_start ? 'on' : 'off'} />
          </Section>
          <Section name="Paths">
            <Row name="All folders usable" value={data.paths.ok ? 'yes' : 'no'} />
            <Row name="One volume" value={data.paths.same_filesystem ? 'yes' : 'no'} />
            {data.paths.checks.map((check) => (
              <Row
                key={check.path}
                name={check.ok ? 'ok' : 'failed'}
                value={
                  <span className="font-mono">
                    {check.path}
                    {check.error ? ` — ${check.error}` : ''}
                  </span>
                }
              />
            ))}
          </Section>
          <Section name="Hardware">
            <Row name="Render device" value={data.transcode.device_path} />
            <Row name="Result" value={data.transcode.message} />
            <Row name="Fully tested" value={data.transcode.tested ? 'yes' : 'not yet'} />
            {data.transcode.profiles.map((profile) => (
              <Row
                key={profile.profile}
                name={profile.profile}
                value={profile.ok ? 'works' : (profile.error ?? 'failed')}
              />
            ))}
          </Section>
          <Section name="Database">
            <Row name="File" value={<span className="font-mono">{data.database.path}</span>} />
            <Row name="Size" value={megabytes(data.database.size_bytes)} />
            <Row name="Last backup" value={data.database.last_backup ?? 'none yet'} />
          </Section>
          <Section name="Library">
            <Row name="Radarr" value={arrLine(data.radarr)} />
            <Row name="Sonarr" value={arrLine(data.sonarr)} />
            <Row name="Concurrent downloads" value={data.concurrency.downloads} />
            <Row name="Concurrent transcodes" value={data.concurrency.transcodes} />
          </Section>
        </>
      )}
    </div>
  )
}
