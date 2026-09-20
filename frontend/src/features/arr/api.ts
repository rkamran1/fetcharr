import { request } from '@/api/client'

import type { ArrTestResult, RadarrMovieList } from './types'

export const radarrMoviesQueryKey = (query: string, missing = false) =>
  ['arr', 'radarr', 'movies', query, missing] as const

/**
 * `missing` narrows the library to what Radarr monitors but has no file for (§5 step 2a).
 * `refresh` skips fetcharr's five-minute cache and re-reads Radarr now.
 */
export const searchRadarrMovies = (query: string, missing = false, refresh = false) =>
  request<RadarrMovieList>(
    'GET',
    `/api/arr/radarr/movies?q=${encodeURIComponent(query)}` +
      `${missing ? '&missing=true' : ''}${refresh ? '&refresh=true' : ''}`,
  )

export const testRadarr = () => request<ArrTestResult>('POST', '/api/arr/radarr/test')
