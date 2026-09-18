import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router'

import { getAuthState, setupAccount } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { MIN_PASSWORD_LENGTH, passwordProblem } from '@/lib/passwords'
import { authStateQueryKey, meQueryKey } from '@/lib/queryClient'

export default function SetupPage() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const state = useQuery({ queryKey: authStateQueryKey, queryFn: getAuthState })
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const mutation = useMutation({
    mutationFn: setupAccount,
    onSuccess: (me) => {
      queryClient.setQueryData(authStateQueryKey, { setup_required: false })
      queryClient.setQueryData(meQueryKey, me)
      navigate('/', { replace: true })
    },
  })

  // After our own successful setup, onSuccess navigates home; don't race it to /login.
  if (state.data && !state.data.setup_required && !mutation.isSuccess) {
    return <Navigate to="/login" replace />
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const found = passwordProblem(password, confirm)
    setProblem(found)
    if (!found) mutation.mutate({ username, password })
  }

  const error = problem ?? (mutation.isError ? mutation.error.message : null)

  return (
    <main className="flex min-h-svh items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>
            <h1 className="text-2xl">Create your account</h1>
          </CardTitle>
          <CardDescription>fetcharr has a single account. You can change the password later in Settings.</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="flex flex-col gap-4" onSubmit={submit}>
            <div className="flex flex-col gap-2">
              <Label htmlFor="username">Username</Label>
              <Input
                id="username"
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                maxLength={64}
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={MIN_PASSWORD_LENGTH}
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="confirm">Repeat password</Label>
              <Input
                id="confirm"
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
            <Button type="submit" disabled={mutation.isPending}>
              Create account
            </Button>
          </form>
        </CardContent>
      </Card>
    </main>
  )
}
