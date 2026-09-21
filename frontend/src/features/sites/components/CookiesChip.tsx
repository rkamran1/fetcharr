import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'

import { listSites, sitesQueryKey } from '../api'
import { daysUntil } from '../dates'
import type { Site } from '../types'

type Props = {
  /** The site the inspected URL belongs to, from the inspect result. */
  siteKey: string | null
  useCookies: boolean
  onChange: (useCookies: boolean) => void
}

function expiry(site: Site): string {
  if (!site.earliest_expiry) return ''
  const days = daysUntil(site.earliest_expiry)
  if (days <= 0) return ' (expired)'
  return ` (expires in ${days} ${days === 1 ? 'day' : 'days'})`
}

/**
 * Step 2's cookies chip: which site's cookies this download uses, with a Skip toggle (§8).
 * Nothing shows when the site has no cookies, since there is nothing to skip.
 */
export default function CookiesChip({ siteKey, useCookies, onChange }: Props) {
  const sites = useQuery({
    queryKey: sitesQueryKey,
    queryFn: listSites,
    enabled: !!siteKey,
  })
  const site = sites.data?.find((s) => s.key === siteKey)
  if (!site || site.status === 'none') return null

  return (
    <div role="group" aria-label="Cookies" className="flex flex-col gap-1 text-sm">
      <p className={useCookies ? '' : 'text-muted-foreground line-through'}>
        Using {site.key} cookies{expiry(site)}
      </p>
      {site.status === 'flagged' && (
        <p className="text-destructive">
          These cookies may be invalid.{' '}
          <Link to={`/cookies#${site.key}`} className="underline">
            Check Cookies
          </Link>
        </p>
      )}
      <label className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={!useCookies}
          onChange={(e) => onChange(!e.target.checked)}
        />
        Skip cookies
      </label>
    </div>
  )
}
