import { cn } from '@/lib/utils'

type Props = {
  /** Radarr's poster URL, or null when it has no artwork for the movie. */
  url: string | null
  className?: string
}

/**
 * A movie's poster, always decorative: the title sits beside or below it everywhere this is
 * used, so an alt text would only duplicate it — and would land in the accessible name of the
 * button wrapping it. Radarr's poster is an absolute TMDB URL, so no API key is involved.
 */
export default function MoviePoster({ url, className }: Props) {
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
