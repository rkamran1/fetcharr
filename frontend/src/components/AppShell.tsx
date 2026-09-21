import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { NavLink, Outlet, useNavigate } from 'react-router'

import { logout } from '@/features/auth'
import { getHealth, healthQueryKey } from '@/features/system'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const NAV = [
  { to: '/', label: 'Home' },
  { to: '/queue', label: 'Queue' },
  { to: '/cookies', label: 'Cookies' },
  { to: '/settings', label: 'Settings' },
]

export default function AppShell() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const health = useQuery({ queryKey: healthQueryKey, queryFn: getHealth })
  const signOut = useMutation({
    mutationFn: logout,
    onSuccess: () => {
      queryClient.clear()
      navigate('/login', { replace: true })
    },
  })

  return (
    <div className="flex min-h-svh flex-col">
      <header className="border-b">
        <div className="mx-auto flex w-full max-w-5xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <span className="text-lg font-semibold">fetcharr</span>
          <nav aria-label="Main" className="order-last flex w-full gap-4 sm:order-none sm:w-auto">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end
                className={({ isActive }) =>
                  cn('text-sm', isActive ? 'font-semibold' : 'text-muted-foreground')
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <Button
            variant="outline"
            size="sm"
            className="ml-auto"
            onClick={() => signOut.mutate()}
            disabled={signOut.isPending}
          >
            Log out
          </Button>
        </div>
      </header>
      <main className="mx-auto w-full max-w-5xl flex-1 p-4">
        <Outlet />
      </main>
      <footer className="text-muted-foreground px-4 py-3 text-center text-xs">
        {health.isSuccess ? `fetcharr ${health.data.version}` : 'fetcharr'}
      </footer>
    </div>
  )
}
