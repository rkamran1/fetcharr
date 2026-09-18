import { MutationCache, QueryCache, QueryClient } from '@tanstack/react-query'

import { ApiError } from '@/api/client'

export const meQueryKey = ['auth', 'me'] as const
export const authStateQueryKey = ['auth', 'state'] as const

export function createQueryClient(): QueryClient {
  // A 401 from any request while signed in means the session is gone: reset the `me`
  // query so the auth guard re-checks and sends the user to the login page.
  const onError = (error: unknown) => {
    if (
      error instanceof ApiError &&
      error.status === 401 &&
      queryClient.getQueryData(meQueryKey) !== undefined
    ) {
      void queryClient.resetQueries({ queryKey: meQueryKey })
    }
  }
  const queryClient: QueryClient = new QueryClient({
    queryCache: new QueryCache({ onError }),
    mutationCache: new MutationCache({ onError }),
    defaultOptions: {
      queries: {
        // Client errors (401, 404, …) won't fix themselves; only retry server/network errors.
        retry: (failureCount, error) =>
          !(error instanceof ApiError && error.status < 500) && failureCount < 3,
      },
    },
  })
  return queryClient
}
