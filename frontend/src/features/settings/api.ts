import { request } from '@/api/client'

import type { AppSettings, SettingsUpdate } from './types'

export const settingsQueryKey = ['settings'] as const

export const getSettings = () => request<AppSettings>('GET', '/api/settings')

export const updateSettings = (body: SettingsUpdate) =>
  request<AppSettings>('PATCH', '/api/settings', body)
