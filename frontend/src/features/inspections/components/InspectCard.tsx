import { Link } from 'react-router'

import { ApiError } from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'

import type { InspectResult, PreviousDownload } from '../types'

type Props = {
  isPending: boolean
  error: Error | null
  data: InspectResult | undefined
}

function formatDuration(seconds: number): string {
  const total = Math.round(seconds)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = String(total % 60).padStart(2, '0')
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`
}

type InspectErrorBody = { needs_cookies?: unknown; site_key?: unknown } | undefined

function needsCookies(error: Error): boolean {
  return error instanceof ApiError && (error.data as InspectErrorBody)?.needs_cookies === true
}

/** The site to add cookies for, so the link lands on its row (§8). */
function siteKey(error: Error): string | null {
  const key = error instanceof ApiError ? (error.data as InspectErrorBody)?.site_key : null
  return typeof key === 'string' ? key : null
}

const TYPE_LABELS: Record<PreviousDownload['media_type'], string> = {
  movie: 'Movie',
  tv: 'TV',
  other: 'Other',
}

const IMPORT_LABELS: Record<PreviousDownload['import_status'], string | null> = {
  'n/a': null,
  pending: 'import pending',
  imported: 'imported',
  not_imported: 'not imported',
  error: 'import error',
}

/** "Already downloaded": each earlier finished download of this same video (§10). */
function PreviousDownloads({ downloads }: { downloads: PreviousDownload[] }) {
  return (
    <section aria-label="Downloaded before" className="flex flex-col gap-1 text-sm">
      <p className="font-medium">⚠ Downloaded before</p>
      <ul className="text-muted-foreground flex flex-col gap-1 text-xs">
        {downloads.map((download) => (
          <li key={download.job_id} className="break-all">
            {[
              download.created_at.slice(0, 10),
              TYPE_LABELS[download.media_type],
              download.path,
              IMPORT_LABELS[download.import_status],
            ]
              .filter(Boolean)
              .join(' · ')}
          </li>
        ))}
      </ul>
    </section>
  )
}

/** What yt-dlp knows about one URL: loading, error, needs-cookies or the video summary. */
export default function InspectCard({ isPending, error, data }: Props) {
  if (isPending) {
    return (
      <Card>
        <CardContent>
          <p role="status" className="text-muted-foreground text-sm">
            Inspecting…
          </p>
        </CardContent>
      </Card>
    )
  }

  if (error) {
    return (
      <Card>
        <CardContent className="flex flex-col gap-1" role="alert">
          {needsCookies(error) ? (
            <>
              <p className="font-medium">This video needs cookies.</p>
              <p className="text-muted-foreground text-sm">
                The site wants a signed-in account (sign-in, age, members-only or private
                video). Add cookies for this site to inspect it.
              </p>
              <Link
                to={siteKey(error) ? `/cookies#${siteKey(error)}` : '/cookies'}
                className="text-sm underline"
              >
                {siteKey(error) ? `Add cookies for ${siteKey(error)}` : 'Add cookies'}
              </Link>
              <p className="text-muted-foreground text-xs">{error.message}</p>
            </>
          ) : (
            <p className="text-destructive text-sm">{error.message}</p>
          )}
        </CardContent>
      </Card>
    )
  }

  if (!data) return null

  return (
    <Card>
      <CardContent className="flex flex-col gap-4 sm:flex-row">
        {data.thumbnail && (
          <img
            src={data.thumbnail}
            alt={data.title ?? 'Thumbnail'}
            className="aspect-video w-full rounded-md object-cover sm:w-64"
          />
        )}
        <div className="flex min-w-0 flex-col gap-2">
          <h2 className="text-lg font-semibold break-words">{data.title ?? 'Untitled'}</h2>
          <p className="text-muted-foreground text-sm">
            {[data.uploader, data.duration != null ? formatDuration(data.duration) : null]
              .filter(Boolean)
              .join(' · ')}
          </p>
          <ul aria-label="Qualities" className="flex flex-wrap gap-1.5">
            {data.video_heights.map((height) => (
              <li key={height}>
                <Badge variant="outline">{height}p</Badge>
              </li>
            ))}
            {data.has_hdr && (
              <li>
                <Badge variant="outline">HDR</Badge>
              </li>
            )}
          </ul>
          <p className="text-sm">
            Stream: <Badge>{data.stream_type.toUpperCase()}</Badge>
          </p>
          {(data.previous_downloads?.length ?? 0) > 0 && (
            <PreviousDownloads downloads={data.previous_downloads!} />
          )}
        </div>
      </CardContent>
    </Card>
  )
}
