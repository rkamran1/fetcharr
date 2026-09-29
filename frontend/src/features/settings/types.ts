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
  /** Every §7.2 template, the stored ones over the defaults. */
  naming_templates: NamingTemplates
  colon_mode: ColonMode
}

/** The eight editable templates (§7.2). */
export type NamingTemplates = {
  movie_folder: string
  movie_file: string
  series_folder: string
  season_folder: string
  specials_folder: string
  standard_episode: string
  daily_episode: string
  other: string
}

export type ColonMode = 'smart' | 'delete' | 'dash' | 'space_dash' | 'space_dash_space'

/** One example path per kind of target, plus why a template could not be used. */
export type NamingPreview = {
  examples: Record<string, string>
  errors: Record<string, string>
}

export type YtdlpUpdate = { old: string | null; new: string | null; output: string }

export type SettingsUpdate = {
  radarr_url?: string
  radarr_api_key?: string
  sonarr_url?: string
  sonarr_api_key?: string
  transcode_quality?: Record<string, number>
  /** A subset of the templates; an empty map resets every one to its §7.2 default. */
  naming_templates?: Partial<NamingTemplates> | Record<string, never>
  colon_mode?: ColonMode
}
