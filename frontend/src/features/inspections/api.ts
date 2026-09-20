import { request } from '@/api/client'

import type { InspectResult } from './types'

export const inspect = (url: string) => request<InspectResult>('POST', '/api/inspect', { url })
