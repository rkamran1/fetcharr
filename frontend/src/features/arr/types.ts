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

/** What the Settings Test button gets back: the version, or why it didn't work. */
export type ArrTestResult = { ok: boolean; version: string | null; error: string | null }
