import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { testRadarr } from '@/features/arr'

import { getSettings, settingsQueryKey, updateSettings } from '../api'

export default function RadarrSettings() {
  const queryClient = useQueryClient()
  const settings = useQuery({ queryKey: settingsQueryKey, queryFn: getSettings })
  const [url, setUrl] = useState<string | null>(null)
  const [apiKey, setApiKey] = useState('')

  const test = useMutation({ mutationFn: testRadarr })
  const save = useMutation({
    mutationFn: updateSettings,
    onSuccess: (data) => {
      queryClient.setQueryData(settingsQueryKey, data)
      setUrl(null)
      setApiKey('')
      test.reset()
    },
  })

  const fromEnv = settings.data?.radarr_from_env ?? false
  const value = url ?? settings.data?.radarr_url ?? ''
  const keySet = settings.data?.radarr_api_key_set ?? false

  const submit = (event: FormEvent) => {
    event.preventDefault()
    save.mutate({ radarr_url: value, ...(apiKey ? { radarr_api_key: apiKey } : {}) })
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>Radarr</h2>
        </CardTitle>
        <CardDescription>
          Where to send movie imports. Radarr must mount the same downloads folder at{' '}
          <code>/web-downloads</code>.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <form className="flex max-w-sm flex-col gap-4" onSubmit={submit}>
          <div className="flex flex-col gap-2">
            <Label htmlFor="radarr-url">Radarr URL</Label>
            <Input
              id="radarr-url"
              type="url"
              inputMode="url"
              placeholder="http://radarr:7878"
              value={value}
              disabled={fromEnv}
              onChange={(e) => setUrl(e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="radarr-api-key">API key</Label>
            <Input
              id="radarr-api-key"
              type="password"
              autoComplete="off"
              // The stored key never comes back, so an empty box means "leave it alone".
              placeholder={keySet ? 'Set — type a new key to replace it' : 'Not set'}
              value={apiKey}
              disabled={fromEnv}
              onChange={(e) => setApiKey(e.target.value)}
            />
          </div>
          {fromEnv && (
            <p className="text-muted-foreground text-sm">
              RADARR_URL and RADARR_API_KEY are set in the environment, so they win over
              anything saved here.
            </p>
          )}
          {save.isError && (
            <p role="alert" className="text-destructive text-sm">
              {save.error.message}
            </p>
          )}
          <div className="flex gap-2">
            <Button type="submit" disabled={save.isPending || fromEnv}>
              Save
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => test.mutate()}
              disabled={test.isPending}
            >
              Test
            </Button>
          </div>
        </form>
        {test.isSuccess && (
          <p role="status" className="text-sm">
            {test.data.ok
              ? `Connected to Radarr ${test.data.version}.`
              : `Radarr didn't answer: ${test.data.error}`}
          </p>
        )}
      </CardContent>
    </Card>
  )
}
