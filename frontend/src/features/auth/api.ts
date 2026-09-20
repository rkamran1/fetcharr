import { request } from '@/api/client'

import type { ApiKey, AuthState, Credentials, Me, PasswordChange } from './types'

export const meQueryKey = ['auth', 'me'] as const
export const authStateQueryKey = ['auth', 'state'] as const

export const getAuthState = () => request<AuthState>('GET', '/api/auth/state')
export const setupAccount = (body: Credentials) => request<Me>('POST', '/api/auth/setup', body)
export const login = (body: Credentials) => request<Me>('POST', '/api/auth/login', body)
export const logout = () => request<void>('POST', '/api/auth/logout')
export const getMe = () => request<Me>('GET', '/api/auth/me')
export const changePassword = (body: PasswordChange) =>
  request<void>('POST', '/api/auth/password', body)
export const regenerateApiKey = () => request<ApiKey>('POST', '/api/auth/api-key')
