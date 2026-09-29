import { request } from '@/api/client'

import type {
  AppSettings,
  ColonMode,
  NamingPreview,
  NamingTemplates,
  SettingsUpdate,
  YtdlpUpdate,
} from './types'

export const settingsQueryKey = ['settings'] as const

export const getSettings = () => request<AppSettings>('GET', '/api/settings')

export const updateSettings = (body: SettingsUpdate) =>
  request<AppSettings>('PATCH', '/api/settings', body)

/** The live example under the template fields; invalid templates come back as errors. */
export const previewNaming = (body: {
  templates?: Partial<NamingTemplates>
  colon_mode?: ColonMode
}) => request<NamingPreview>('POST', '/api/settings/naming/preview', body)

/** `pip install --upgrade yt-dlp` inside the yt-dlp venv (§13.1). */
export const updateYtdlp = () => request<YtdlpUpdate>('POST', '/api/settings/yt-dlp/update')
