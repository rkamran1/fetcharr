export type Health = {
  status: string
  version: string
}

export async function getHealth(): Promise<Health> {
  const response = await fetch('/healthz')
  if (!response.ok) {
    throw new Error(`GET /healthz failed: ${response.status}`)
  }
  return (await response.json()) as Health
}
