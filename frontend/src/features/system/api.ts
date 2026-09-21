import { request } from '@/api/client'

import type { Health, SystemStatus, TranscodeReport } from './types'

/** Outside `/api`, and public by design, so it doesn't go through `request`. */
export async function getHealth(): Promise<Health> {
  const response = await fetch('/healthz')
  if (!response.ok) {
    throw new Error(`GET /healthz failed: ${response.status}`)
  }
  return (await response.json()) as Health
}

export const healthQueryKey = ['healthz'] as const

export const systemStatusQueryKey = ['system', 'status'] as const

export const getSystemStatus = () => request<SystemStatus>('GET', '/api/system/status')

/** Re-runs the QSV/VAAPI self-test: vainfo plus a one-second encode per profile (§13.1). */
export const testHardwareEncode = () =>
  request<TranscodeReport>('POST', '/api/system/transcode-test')
