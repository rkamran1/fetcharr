export type RadarrMovie = {
  id: number
  title: string
  year: number | null
  has_file: boolean
  quality: string | null
}

export type RadarrMovieList = { movies: RadarrMovie[] }

/** What the Settings Test button gets back: the version, or why it didn't work. */
export type ArrTestResult = { ok: boolean; version: string | null; error: string | null }
