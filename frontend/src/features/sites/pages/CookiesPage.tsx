import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { useLocation } from 'react-router'

import { listSites, sitesQueryKey } from '../api'
import AddSiteForm from '../components/AddSiteForm'
import CookieHelp from '../components/CookieHelp'
import SiteRow from '../components/SiteRow'

/** One cookie file per site, applied automatically to that site's URLs (§8, §12). */
export default function CookiesPage() {
  const sites = useQuery({ queryKey: sitesQueryKey, queryFn: listSites })
  const { hash } = useLocation()

  // `/cookies#bilibili` comes from a needs-cookies link: bring that site into view.
  useEffect(() => {
    if (hash && sites.isSuccess) document.getElementById(hash.slice(1))?.scrollIntoView?.()
  }, [hash, sites.isSuccess])

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Cookies</h1>
      {sites.isPending && <p className="text-muted-foreground text-sm">Loading…</p>}
      {sites.isError && (
        <p role="alert" className="text-destructive text-sm">
          {sites.error.message}
        </p>
      )}
      {sites.data?.map((site) => (
        <SiteRow key={site.key} site={site} />
      ))}
      <AddSiteForm />
      <CookieHelp />
    </div>
  )
}
