import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'

import { deleteCookies, deleteSite, sitesQueryKey } from '../api'
import { formatDay } from '../dates'
import type { Site } from '../types'
import StatusBadge from './StatusBadge'
import UploadCookies from './UploadCookies'

/** One site: its status and summary, Upload/Replace, and Delete (§8, §12). */
export default function SiteRow({ site }: { site: Site }) {
  const queryClient = useQueryClient()
  const [uploading, setUploading] = useState(false)
  const [warning, setWarning] = useState<string | null>(null)
  const refresh = () => queryClient.invalidateQueries({ queryKey: sitesQueryKey })

  const removeCookies = useMutation({
    mutationFn: () => deleteCookies(site.key),
    onSuccess: refresh,
  })
  const removeSite = useMutation({
    mutationFn: () => deleteSite(site.key),
    onSuccess: refresh,
  })
  const failed = removeCookies.error ?? removeSite.error
  const hasCookies = site.status !== 'none'

  return (
    // The id is the Cookies link's anchor (`/cookies#youtube`).
    <Card id={site.key} role="region" aria-label={site.label}>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="font-semibold">{site.label}</h2>
          <StatusBadge status={site.status} />
          <span className="text-muted-foreground min-w-0 text-xs break-all">
            {site.domains.join(', ')}
          </span>
        </div>

        {hasCookies && (
          <dl className="text-muted-foreground grid grid-cols-[auto_1fr] gap-x-3 text-sm">
            <dt>Cookies</dt>
            <dd>{site.cookie_count}</dd>
            <dt>Expires</dt>
            <dd>{site.earliest_expiry ? formatDay(site.earliest_expiry) : 'Session only'}</dd>
            <dt>Last used</dt>
            <dd>{site.last_used_at ? formatDay(site.last_used_at) : 'Never'}</dd>
          </dl>
        )}
        {site.status === 'flagged' && (
          <p className="text-destructive text-sm">
            A download failed with a sign-in error while these cookies were in use. Export a fresh
            file and replace it.
          </p>
        )}

        {warning && (
          <p role="status" className="text-sm text-amber-600 dark:text-amber-400">
            {warning}
          </p>
        )}
        {failed && (
          <p role="alert" className="text-destructive text-sm">
            {failed.message}
          </p>
        )}

        {uploading ? (
          <UploadCookies
            site={site}
            onDone={(message) => {
              setWarning(message)
              setUploading(!!message)
            }}
          />
        ) : (
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              onClick={() => {
                setWarning(null)
                setUploading(true)
              }}
            >
              {hasCookies ? 'Replace' : 'Upload'}
            </Button>
            {hasCookies && (
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => removeCookies.mutate()}
                disabled={removeCookies.isPending}
              >
                Delete cookies
              </Button>
            )}
            {!site.builtin && (
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => removeSite.mutate()}
                disabled={removeSite.isPending}
              >
                Delete site
              </Button>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
