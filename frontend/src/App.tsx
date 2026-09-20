import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router'

import { ApiError } from '@/api/client'
import AppShell from '@/components/AppShell'
import {
  authStateQueryKey,
  getAuthState,
  getMe,
  LoginPage,
  meQueryKey,
  SetupPage,
} from '@/features/auth'
import { QueuePage } from '@/features/jobs'
import { MovieWizardPage, OtherWizardPage } from '@/features/requests'
import { SettingsPage } from '@/features/settings'
import HomePage from '@/pages/HomePage'

function Centered({ children }: { children: ReactNode }) {
  return (
    <main className="text-muted-foreground flex min-h-svh items-center justify-center p-4">
      {children}
    </main>
  )
}

/** Renders its children only when signed in; otherwise sends the user to setup or login. */
function RequireAuth({ children }: { children: ReactNode }) {
  const me = useQuery({ queryKey: meQueryKey, queryFn: getMe })
  const unauthenticated = me.error instanceof ApiError && me.error.status === 401
  const state = useQuery({
    queryKey: authStateQueryKey,
    queryFn: getAuthState,
    enabled: unauthenticated,
  })

  if (unauthenticated) {
    if (state.isPending) return <Centered>Loading…</Centered>
    return <Navigate to={state.data?.setup_required ? '/setup' : '/login'} replace />
  }
  if (me.isSuccess) return children
  if (me.isError) return <Centered>Server unreachable.</Centered>
  return <Centered>Loading…</Centered>
}

export default function App() {
  return (
    <Routes>
      <Route path="/setup" element={<SetupPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route index element={<HomePage />} />
        <Route path="download/movie" element={<MovieWizardPage />} />
        <Route path="download/other" element={<OtherWizardPage />} />
        <Route path="queue" element={<QueuePage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
