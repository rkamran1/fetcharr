import { request } from '@/api/client'

import type { ArrTestResult, RadarrMovieList, SonarrEpisodeList, SonarrSeriesList } from './types'

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

export const sonarrSeriesQueryKey = (query: string, missing = false) =>
  ['arr', 'sonarr', 'series', query, missing] as const

/**
 * Sonarr's own series list, cached there for five minutes (§5 step 2b).
 * `missing` keeps only the monitored series short of an episode that has already aired.
 * `refresh` skips fetcharr's cache and re-reads Sonarr now.
 */
export const searchSonarrSeries = (query: string, missing = false, refresh = false) =>
  request<SonarrSeriesList>(
    'GET',
    `/api/arr/sonarr/series?q=${encodeURIComponent(query)}` +
      `${missing ? '&missing=true' : ''}${refresh ? '&refresh=true' : ''}`,
  )

export const sonarrEpisodesQueryKey = (seriesId: number, season: number | null) =>
  ['arr', 'sonarr', 'episodes', seriesId, season] as const

/** One season's episodes, so the mapping table names them the way Sonarr does. */
export const listSonarrEpisodes = (seriesId: number, season: number | null) =>
  request<SonarrEpisodeList>(
    'GET',
    `/api/arr/sonarr/series/${seriesId}/episodes${season === null ? '' : `?season=${season}`}`,
  )

export const testSonarr = () => request<ArrTestResult>('POST', '/api/arr/sonarr/test')
