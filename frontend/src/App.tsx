import { useQuery } from '@tanstack/react-query'

import { getHealth } from '@/api/client'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

export default function App() {
  const health = useQuery({ queryKey: ['healthz'], queryFn: getHealth })

  return (
    <main className="flex min-h-svh items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-2xl">fetcharr</CardTitle>
          <CardDescription>
            {health.isSuccess && `version ${health.data.version}`}
            {health.isPending && 'connecting…'}
            {health.isError && 'server unreachable'}
          </CardDescription>
        </CardHeader>
      </Card>
    </main>
  )
}
