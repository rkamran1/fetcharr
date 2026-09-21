import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { radarrMoviesQueryKey, searchRadarrMovies, type RadarrMovie } from '@/features/arr'

import type { MovieMedia } from '../types'
import Poster from './Poster'

const WARNING =
  "Radarr doesn't have this movie, so the import will fail. Add it in Radarr first " +
  '(then Retry import), or download as Other.'

type Props = {
  /** The cleaned video title, used as the first search (requirements §5 step 2a). */
  initialQuery: string
  value: MovieMedia | null
  onChange: (media: MovieMedia | null) => void
}

export default function RadarrMoviePicker({ initialQuery, value, onChange }: Props) {
  const [query, setQuery] = useState(initialQuery)
  // A movie typed by hand before ("download again") comes back as typed.
  const [manual, setManual] = useState(value !== null && value.radarr_movie_id === null)
  const [picked, setPicked] = useState<RadarrMovie | null>(null)

  const movies = useQuery({
    queryKey: radarrMoviesQueryKey(query.trim()),
    queryFn: () => searchRadarrMovies(query.trim()),
    enabled: !manual && query.trim().length > 0,
  })

  const choose = (movie: RadarrMovie) => {
    setPicked(movie)
    onChange({ radarr_movie_id: movie.id, title: movie.title, year: movie.year })
  }

  const typeManually = (title: string, year: string) => {
    const parsed = Number.parseInt(year)
    onChange(
      title.trim()
        ? {
            radarr_movie_id: null,
            title: title.trim(),
            year: Number.isFinite(parsed) ? parsed : null,
          }
        : null,
    )
  }

  if (manual) {
    return (
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-4 sm:flex-row">
          <div className="flex flex-1 flex-col gap-2">
            <Label htmlFor="movie-title">Movie title</Label>
            <Input
              id="movie-title"
              value={value?.title ?? ''}
              onChange={(e) => typeManually(e.target.value, String(value?.year ?? ''))}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="movie-year">Year</Label>
            <Input
              id="movie-year"
              type="number"
              className="w-28"
              value={value?.year ?? ''}
              onChange={(e) => typeManually(value?.title ?? '', e.target.value)}
            />
          </div>
        </div>
        <p role="alert" className="text-sm">
          ⚠ {WARNING}
        </p>
        <Button
          type="button"
          variant="outline"
          className="self-start"
          onClick={() => {
            setManual(false)
            onChange(null)
          }}
        >
          Search Radarr instead
        </Button>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <Label htmlFor="movie-search">Movie in Radarr</Label>
        <Input
          id="movie-search"
          value={query}
          placeholder="Search your Radarr library"
          onChange={(e) => {
            setQuery(e.target.value)
            setPicked(null)
            onChange(null)
          }}
        />
      </div>

      {movies.isError && (
        <p role="alert" className="text-destructive text-sm">
          {movies.error.message}
        </p>
      )}

      {/* Picked here, or handed in already picked ("download again"). */}
      {value ? (
        <div className="flex items-start gap-4">
          <Poster url={picked?.poster ?? null} className="w-20" />
          <p className="text-sm">
            <span className="font-medium">
              {value.title}
              {value.year ? ` (${value.year})` : ''}
            </span>
            {picked?.has_file && (
              <span className="text-muted-foreground">
                {' '}
                — Radarr already has this at {picked.quality ?? 'an unknown quality'}
              </span>
            )}
          </p>
        </div>
      ) : (
        movies.isSuccess &&
        (movies.data.movies.length === 0 ? (
          <p className="text-muted-foreground text-sm">Nothing in Radarr matches.</p>
        ) : (
          // The same poster grid as the Missing tab, so the two ways in look like one app.
          <ul
            aria-label="Radarr movies"
            className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4"
          >
            {movies.data.movies.map((movie) => (
              <li key={movie.id}>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => choose(movie)}
                  className="h-auto w-full flex-col items-stretch gap-0 overflow-hidden p-0 text-left"
                >
                  <Poster url={movie.poster} className="w-full rounded-none" />
                  <span className="w-full px-2 py-2 text-xs leading-snug whitespace-normal">
                    {movie.title}
                    {movie.year ? ` (${movie.year})` : ''}
                  </span>
                </Button>
              </li>
            ))}
          </ul>
        ))
      )}

      <Button
        type="button"
        variant="outline"
        className="self-start"
        onClick={() => {
          setManual(true)
          setPicked(null)
          onChange(null)
        }}
      >
        It&apos;s not in Radarr
      </Button>
    </div>
  )
}
