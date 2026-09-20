import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { testRadarr, testSonarr, type ArrTestResult } from '@/features/arr'

import { getSettings, settingsQueryKey, updateSettings } from '../api'
import type { AppSettings, SettingsUpdate } from '../types'

type App = {
  name: string
  /** The `<input id>` prefix and the settings keys, e.g. `radarr_url`. */
  key: 'radarr' | 'sonarr'
  placeholder: string
  imports: string
  test: () => Promise<ArrTestResult>
}

const APPS: Record<'radarr' | 'sonarr', App> = {
  radarr: {
    name: 'Radarr',
    key: 'radarr',
    placeholder: 'http://radarr:7878',
    imports: 'movie imports',
    test: testRadarr,
  },
  sonarr: {
    name: 'Sonarr',
    key: 'sonarr',
    placeholder: 'http://sonarr:8989',
    imports: 'episode imports',
    test: testSonarr,
  },
}

/** One arr connection: URL, API key and a Test button (§7.5). The two are identical. */
export default function ArrSettings({ app: which }: { app: 'radarr' | 'sonarr' }) {
  const app = APPS[which]
  const queryClient = useQueryClient()
  const settings = useQuery({ queryKey: settingsQueryKey, queryFn: getSettings })
  const [url, setUrl] = useState<string | null>(null)
  const [apiKey, setApiKey] = useState('')

  const test = useMutation({ mutationFn: app.test })
  const save = useMutation({
    mutationFn: updateSettings,
    onSuccess: (data) => {
      queryClient.setQueryData(settingsQueryKey, data)
      setUrl(null)
      setApiKey('')
      test.reset()
    },
  })

  const stored = settings.data
  const fromEnv = stored?.[`${app.key}_from_env` as keyof AppSettings] === true
  const value = url ?? (stored?.[`${app.key}_url` as keyof AppSettings] as string | null) ?? ''
  const keySet = stored?.[`${app.key}_api_key_set` as keyof AppSettings] === true

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const body = {
      [`${app.key}_url`]: value,
      ...(apiKey ? { [`${app.key}_api_key`]: apiKey } : {}),
    } as SettingsUpdate
    save.mutate(body)
  }

  return (
    // Named, because the page holds one of these per arr app.
    <Card role="region" aria-label={app.name}>
      <CardHeader>
        <CardTitle>
          <h2>{app.name}</h2>
        </CardTitle>
        <CardDescription>
          Where to send {app.imports}. {app.name} must mount the same downloads folder at{' '}
          <code>/web-downloads</code>.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <form className="flex max-w-sm flex-col gap-4" onSubmit={submit}>
          <div className="flex flex-col gap-2">
            <Label htmlFor={`${app.key}-url`}>{app.name} URL</Label>
            <Input
              id={`${app.key}-url`}
              type="url"
              inputMode="url"
              placeholder={app.placeholder}
              value={value}
              disabled={fromEnv}
              onChange={(e) => setUrl(e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor={`${app.key}-api-key`}>API key</Label>
            <Input
              id={`${app.key}-api-key`}
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
              {app.name.toUpperCase()}_URL and {app.name.toUpperCase()}_API_KEY are set in the
              environment, so they win over anything saved here.
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
              ? `Connected to ${app.name} ${test.data.version}.`
              : `${app.name} didn't answer: ${test.data.error}`}
          </p>
        )}
      </CardContent>
    </Card>
  )
}
