import { request } from '@/api/client'

import type {
  CreateRequest,
  CreatedRequest,
  PathPreview,
  PreviewRequest,
  RequestFilters,
  RequestPage,
  RequestRead,
} from './types'

export const requestsQueryKey = ['requests'] as const
export const requestListQueryKey = (filters: RequestFilters) => ['requests', 'list', filters] as const
export const requestQueryKey = (id: string) => ['requests', id] as const

export const previewQueryKey = (body: PreviewRequest) => ['preview', body] as const

export const createRequest = (body: CreateRequest) =>
  request<CreatedRequest>('POST', '/api/requests', body)

export const previewPath = (body: PreviewRequest) =>
  request<PathPreview>('POST', '/api/preview', body)

/** History (§11): only the filters that are set go into the query string. */
export const listRequests = (filters: RequestFilters) => {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== '') params.set(key, String(value))
  }
  const query = params.toString()
  return request<RequestPage>('GET', `/api/requests${query ? `?${query}` : ''}`)
}

export const getRequest = (id: string) => request<RequestRead>('GET', `/api/requests/${id}`)
