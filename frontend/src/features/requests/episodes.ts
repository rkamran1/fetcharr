/**
 * What "missing" means for a Sonarr season (requirements §5 step 2b). Pure functions.
 *
 * Missing is what the library lacks: episodes Sonarr knows about and has no file for.
 * Deliberately **not** Sonarr's own Wanted view, which counts only monitored episodes —
 * a series added unmonitored reports nothing wanted and is exactly the one a person came
 * here to fill (checked against Sonarr 4.0.20 in the M6 review).
 */
import type { SonarrEpisode, SonarrSeason, SonarrSeries } from '@/features/arr'

/** Episodes Sonarr knows about in this season and has no file for. */
export function missingInSeason(season: SonarrSeason): number {
  return Math.max(season.total_episode_count - season.episode_file_count, 0)
}


/** The same across every season, which is what makes a series "missing" in the list. */
export function missingEpisodes(series: SonarrSeries): number {
  return series.seasons.reduce((total, season) => total + missingInSeason(season), 0)
}

/** `Specials`, or `Season 2` — what Sonarr calls the folder, so the UI agrees with it (§7.2). */
export function seasonLabel(season: number): string {
  return season === 0 ? 'Specials' : `Season ${season}`
}

/**
 * How one episode reads on its card: `S01E05 · The Fifth One · 2024-03-15`, or the air date
 * first for a daily series, which is how Sonarr numbers those (§7.2).
 */
export function episodeLabel(episode: SonarrEpisode, daily: boolean): string {
  const code = `S${String(episode.season).padStart(2, '0')}E${String(episode.number).padStart(2, '0')}`
  const parts = daily ? [episode.air_date ?? code, episode.title] : [code, episode.title]
  if (!daily && episode.air_date) parts.push(episode.air_date)
  return parts.filter(Boolean).join(' · ')
}
