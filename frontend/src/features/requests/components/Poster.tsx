import { cn } from '@/lib/utils'

type Props = {
  /** Radarr's or Sonarr's poster URL, or null when it has no artwork for this title. */
  url: string | null
  className?: string
}

/**
 * A movie's or series' poster, always decorative: the title sits beside or below it
 * everywhere this is used, so an alt text would only duplicate it — and would land in the
 * accessible name of the button wrapping it. Both apps hand out an absolute, public artwork
 * URL (TMDB, TheTVDB), so no API key is involved.
 */
export default function Poster({ url, className }: Props) {
  const shape = cn('aspect-[2/3] shrink-0 rounded object-cover', className)

  if (!url) {
    return (
      <span
        aria-hidden="true"
        className={cn(
          shape,
          'bg-muted text-muted-foreground flex items-center justify-center text-2xl',
        )}
      >
        ?
      </span>
    )
  }
  return <img src={url} alt="" loading="lazy" className={shape} />
}
