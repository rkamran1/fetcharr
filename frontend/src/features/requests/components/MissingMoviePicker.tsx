import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { radarrMoviesQueryKey, searchRadarrMovies, type RadarrMovie } from '@/features/arr'

import type { MovieMedia } from '../types'
import Poster from './Poster'

type Props = {
  value: MovieMedia | null
  onChange: (media: MovieMedia | null) => void
}

/** The other way into the Movie wizard: pick what Radarr is missing, then give it a URL. */
export default function MissingMoviePicker({ value, onChange }: Props) {
  const [query, setQuery] = useState('')
  // The poster isn't part of MovieMedia (that shape is the request body), so the chosen
  // movie is kept here to carry its artwork into the confirmation view.
  const [picked, setPicked] = useState<RadarrMovie | null>(null)
  const queryClient = useQueryClient()
  const key = radarrMoviesQueryKey(query.trim(), true)

  // The empty query is the whole missing list, which is the point of this tab.
  const movies = useQuery({
    queryKey: key,
    queryFn: () => searchRadarrMovies(query.trim(), true),
  })

  // fetcharr caches Radarr's library for five minutes, so a movie just added there needs
  // a way in without waiting it out. The answer lands in the same cache entry.
  const refresh = useMutation({
    mutationFn: () => searchRadarrMovies(query.trim(), true, true),
    onSuccess: (data) => queryClient.setQueryData(key, data),
  })

  const choose = (movie: RadarrMovie) => {
    setPicked(movie)
    onChange({ radarr_movie_id: movie.id, title: movie.title, year: movie.year })
  }

  if (value) {
    // Only trust the kept movie if it is still the one selected (the page can clear it).
    const poster = picked?.id === value.radarr_movie_id ? picked.poster : null
    return (
      <div className="flex items-start gap-4">
        <Poster url={poster} className="w-20" />
        <div className="flex flex-col items-start gap-2">
          <p className="text-sm">
            <span className="font-medium">
              {value.title}
              {value.year ? ` (${value.year})` : ''}
            </span>
            <span className="text-muted-foreground">
              {' '}
              — Radarr is monitoring this and has no file
            </span>
          </p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              setPicked(null)
              onChange(null)
            }}
          >
            Pick a different movie
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <Label htmlFor="missing-search">Movie missing in Radarr</Label>
        <div className="flex gap-2">
          <Input
            id="missing-search"
            className="flex-1"
            value={query}
            placeholder="Search the movies Radarr is missing"
            onChange={(e) => setQuery(e.target.value)}
          />
          <Button
            type="button"
            variant="outline"
            onClick={() => refresh.mutate()}
            disabled={refresh.isPending}
          >
            {refresh.isPending ? 'Refreshing…' : 'Refresh'}
          </Button>
        </div>
        <p className="text-muted-foreground text-xs">
          Radarr&apos;s library is cached for five minutes. Refresh after adding a movie there.
        </p>
      </div>

      {(movies.isError || refresh.isError) && (
        <p role="alert" className="text-destructive text-sm">
          {(movies.error ?? refresh.error)?.message}
        </p>
      )}

      {movies.isSuccess &&
        (movies.data.movies.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            Radarr isn&apos;t missing anything that matches.
          </p>
        ) : (
          // Mobile-first (§12): two posters across on a phone, more as the screen allows.
          <ul
            aria-label="Missing movies"
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
        ))}
    </div>
  )
}
