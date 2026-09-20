import { request } from '@/api/client'

import type { ArrTestResult, RadarrMovieList } from './types'

export const radarrMoviesQueryKey = (query: string) => ['arr', 'radarr', 'movies', query] as const

export const searchRadarrMovies = (query: string) =>
  request<RadarrMovieList>('GET', `/api/arr/radarr/movies?q=${encodeURIComponent(query)}`)

export const testRadarr = () => request<ArrTestResult>('POST', '/api/arr/radarr/test')
