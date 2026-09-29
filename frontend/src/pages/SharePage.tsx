import { Link, useSearchParams } from 'react-router'

import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { sharePath } from '@/features/requests'

/** The first URL in the text Android hands over, for apps that share a sentence, not a link. */
function firstUrl(text: string | null): string | null {
  const match = text?.match(/https?:\/\/\S+/)
  return match ? match[0] : null
}

const TYPES = [
  {
    mediaType: 'other' as const,
    name: 'Other',
    description: 'Any video, straight into completed/other. No Radarr or Sonarr.',
  },
  {
    mediaType: 'movie' as const,
    name: 'Movie',
    description: 'Into completed/movies, then Radarr moves it into your library.',
  },
  {
    mediaType: 'tv' as const,
    name: 'TV Show',
    description: 'Pick the series and episode, then Sonarr moves it into your library.',
  },
]

/**
 * Where the PWA's `share_target` lands (§12): a link shared from another app, and the
 * three types to send it to. Android puts the link in `url`, or inside `text` when the
 * sharing app sends a sentence.
 */
export default function SharePage() {
  const [params] = useSearchParams()
  const shared = params.get('url')?.trim() || firstUrl(params.get('text'))

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Shared link</h1>
      {shared ? (
        <p className="text-muted-foreground font-mono text-sm break-all">{shared}</p>
      ) : (
        <p role="alert" className="text-sm">
          No link came through. Paste it into one of the wizards instead.
        </p>
      )}
      <div className="grid gap-4 sm:grid-cols-3">
        {TYPES.map((type) => (
          <Link
            key={type.mediaType}
            to={shared ? sharePath(type.mediaType, shared) : `/download/${type.mediaType}`}
            className="rounded-xl focus-visible:ring-2"
          >
            <Card className="hover:border-primary h-full transition-colors">
              <CardHeader>
                <CardTitle>
                  <h2 className="text-lg">{type.name}</h2>
                </CardTitle>
                <CardDescription>{type.description}</CardDescription>
              </CardHeader>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  )
}
