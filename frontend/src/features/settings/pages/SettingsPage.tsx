import { useMutation } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'

import { changePassword, regenerateApiKey } from '@/features/auth'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { MIN_PASSWORD_LENGTH, passwordProblem } from '@/lib/passwords'

import ArrSettings from '../components/ArrSettings'
import TranscodeSettings from '../components/TranscodeSettings'

function ChangePassword() {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const mutation = useMutation({
    mutationFn: changePassword,
    onSuccess: () => {
      setCurrent('')
      setNext('')
      setConfirm('')
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const found = passwordProblem(next, confirm)
    setProblem(found)
    if (!found) mutation.mutate({ current_password: current, new_password: next })
  }

  const error = problem ?? (mutation.isError ? mutation.error.message : null)

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>Change password</h2>
        </CardTitle>
        <CardDescription>Other devices are signed out; this one stays signed in.</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="flex max-w-sm flex-col gap-4" onSubmit={submit}>
          <div className="flex flex-col gap-2">
            <Label htmlFor="current-password">Current password</Label>
            <Input
              id="current-password"
              type="password"
              autoComplete="current-password"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              required
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="new-password">New password</Label>
            <Input
              id="new-password"
              type="password"
              autoComplete="new-password"
              value={next}
              onChange={(e) => setNext(e.target.value)}
              required
              minLength={MIN_PASSWORD_LENGTH}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="confirm-password">Repeat new password</Label>
            <Input
              id="confirm-password"
              type="password"
              autoComplete="new-password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              required
            />
          </div>
          {error && (
            <p role="alert" className="text-destructive text-sm">
              {error}
            </p>
          )}
          {mutation.isSuccess && !error && <p role="status" className="text-sm">Password changed.</p>}
          <Button type="submit" className="self-start" disabled={mutation.isPending}>
            Change password
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}

function ApiKeySection() {
  // Held in component state only: the key is shown once and gone when you leave the page.
  const [apiKey, setApiKey] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const mutation = useMutation({
    mutationFn: regenerateApiKey,
    onSuccess: (data) => {
      setApiKey(data.api_key)
      setCopied(false)
    },
  })

  const copy = async () => {
    if (!apiKey) return
    await navigator.clipboard.writeText(apiKey)
    setCopied(true)
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>API key</h2>
        </CardTitle>
        <CardDescription>
          Send it as the <code>X-Api-Key</code> header. Regenerating replaces the old key.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {apiKey && (
          <div className="flex flex-col gap-2">
            <Label htmlFor="api-key">New API key (copy it now: it won&apos;t be shown again)</Label>
            <div className="flex gap-2">
              <Input id="api-key" readOnly value={apiKey} className="font-mono" />
              <Button type="button" variant="outline" onClick={copy}>
                {copied ? 'Copied' : 'Copy'}
              </Button>
            </div>
          </div>
        )}
        {mutation.isError && (
          <p role="alert" className="text-destructive text-sm">
            {mutation.error.message}
          </p>
        )}
        <Button
          type="button"
          className="self-start"
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending}
        >
          Regenerate API key
        </Button>
      </CardContent>
    </Card>
  )
}

export default function SettingsPage() {
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-xl font-semibold">Settings</h1>
      <ArrSettings app="radarr" />
      <ArrSettings app="sonarr" />
      <TranscodeSettings />
      <ChangePassword />
      <ApiKeySection />
    </div>
  )
}
