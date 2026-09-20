import { request } from '@/api/client'

import type { CreateRequest, CreatedRequest, PathPreview, PreviewRequest } from './types'

export const previewQueryKey = (body: PreviewRequest) => ['preview', body] as const

export const createRequest = (body: CreateRequest) =>
  request<CreatedRequest>('POST', '/api/requests', body)

export const previewPath = (body: PreviewRequest) =>
  request<PathPreview>('POST', '/api/preview', body)
