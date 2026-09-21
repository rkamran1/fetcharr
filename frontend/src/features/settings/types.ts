/** The stored settings, with every secret reported only as set or not set (§7.5). */
export type AppSettings = {
  radarr_url: string | null
  radarr_api_key_set: boolean
  radarr_from_env: boolean
  sonarr_url: string | null
  sonarr_api_key_set: boolean
  sonarr_from_env: boolean
  /** The default quality per transcode profile; the scales differ, so it is per profile. */
  transcode_quality: Record<string, number>
}

export type SettingsUpdate = {
  radarr_url?: string
  radarr_api_key?: string
  sonarr_url?: string
  sonarr_api_key?: string
  transcode_quality?: Record<string, number>
}
