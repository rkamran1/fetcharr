import type { Health } from './types'

/** Outside `/api`, and public by design, so it doesn't go through `request`. */
export async function getHealth(): Promise<Health> {
  const response = await fetch('/healthz')
  if (!response.ok) {
    throw new Error(`GET /healthz failed: ${response.status}`)
  }
  return (await response.json()) as Health
}

export const healthQueryKey = ['healthz'] as const
