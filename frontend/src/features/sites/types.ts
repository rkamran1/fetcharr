/** How healthy a site's stored cookies are (§8). */
export type CookieStatus = 'none' | 'valid' | 'expiring' | 'expired' | 'flagged'

/** One site and its cookie summary; the contents are never sent back. */
export type Site = {
  key: string
  label: string
  domains: string[]
  builtin: boolean
  status: CookieStatus
  cookie_count: number | null
  /** Naive UTC timestamps, as the backend stores them. */
  earliest_expiry: string | null
  last_used_at: string | null
  uploaded_at: string | null
}

export type SiteCreate = { key: string; domains: string[] }

export type CookiesUploaded = { site: Site; warning: string | null }
