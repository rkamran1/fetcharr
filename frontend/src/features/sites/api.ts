import { request } from '@/api/client'

import type { CookiesUploaded, Site, SiteCreate } from './types'

export const sitesQueryKey = ['sites'] as const

export const listSites = () => request<Site[]>('GET', '/api/sites')

export const createSite = (body: SiteCreate) => request<Site>('POST', '/api/sites', body)

export const deleteSite = (key: string) => request<void>('DELETE', `/api/sites/${key}`)

/** The file's text either way: a chosen file is read in the browser, so upload = paste. */
export const uploadCookies = (key: string, text: string) =>
  request<CookiesUploaded>('PUT', `/api/sites/${key}/cookies`, { text })

export const deleteCookies = (key: string) => request<void>('DELETE', `/api/sites/${key}/cookies`)
