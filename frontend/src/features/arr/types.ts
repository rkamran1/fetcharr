export type RadarrMovie = {
  id: number
  title: string
  year: number | null
  monitored: boolean
  has_file: boolean
  quality: string | null
  /** Radarr's poster, absolute and public, so the browser can load it directly. */
  poster: string | null
}

export type RadarrMovieList = { movies: RadarrMovie[] }

/** How a series numbers its episodes: `S01E05`, or by air date (§5 step 2b). */
export type Numbering = 'standard' | 'daily'

export type SonarrSeason = {
  number: number
  episode_file_count: number
  /** Episodes that have aired and are monitored; the gap to the file count is "missing". */
  episode_count: number
  total_episode_count: number
}

export type SonarrSeries = {
  id: number
  title: string
  series_type: Numbering
  monitored: boolean
  seasons: SonarrSeason[]
  /** Sonarr's poster, absolute and public, exactly like Radarr's. */
  poster: string | null
}

export type SonarrSeriesList = { series: SonarrSeries[] }

export type SonarrEpisode = {
  id: number
  season: number
  number: number
  title: string
  /** `YYYY-MM-DD`, or null for an episode Sonarr has no date for. */
  air_date: string | null
  has_file: boolean
  quality: string | null
}

export type SonarrEpisodeList = { episodes: SonarrEpisode[] }

/** What the Settings Test button gets back: the version, or why it didn't work. */
export type ArrTestResult = { ok: boolean; version: string | null; error: string | null }
