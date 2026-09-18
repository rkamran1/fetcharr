import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router'

import { getAuthState, login } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { authStateQueryKey, meQueryKey } from '@/lib/queryClient'

export default function LoginPage() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const state = useQuery({ queryKey: authStateQueryKey, queryFn: getAuthState })
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const mutation = useMutation({
    mutationFn: login,
    onSuccess: (me) => {
      queryClient.setQueryData(meQueryKey, me)
      navigate('/', { replace: true })
    },
  })

  if (state.data?.setup_required) return <Navigate to="/setup" replace />

  const submit = (event: FormEvent) => {
    event.preventDefault()
    mutation.mutate({ username, password })
  }

  return (
    <main className="flex min-h-svh items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>
            <h1 className="text-2xl">Log in</h1>
          </CardTitle>
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
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            {mutation.isError && (
              <p role="alert" className="text-destructive text-sm">
                {mutation.error.message}
              </p>
            )}
            <Button type="submit" disabled={mutation.isPending}>
              Log in
            </Button>
          </form>
        </CardContent>
      </Card>
    </main>
  )
}
