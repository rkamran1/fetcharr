/** The stored settings, with every secret reported only as set or not set (§7.5). */
export type AppSettings = {
  radarr_url: string | null
  radarr_api_key_set: boolean
  radarr_from_env: boolean
}

export type SettingsUpdate = {
  radarr_url?: string
  radarr_api_key?: string
}
