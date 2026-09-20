import { Link } from 'react-router'

import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

export default function HomePage() {
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Home</h1>
      <div className="grid gap-4 sm:grid-cols-3">
        <Link to="/download/other" className="rounded-xl focus-visible:ring-2">
          <Card className="h-full transition-colors hover:border-primary">
            <CardHeader>
              <CardTitle>
                <h2 className="text-lg">Other</h2>
              </CardTitle>
              <CardDescription>
                Any video, straight into <code>completed/other</code>. No Radarr or Sonarr.
              </CardDescription>
            </CardHeader>
          </Card>
        </Link>
        <Link to="/download/movie" className="rounded-xl focus-visible:ring-2">
          <Card className="h-full transition-colors hover:border-primary">
            <CardHeader>
              <CardTitle>
                <h2 className="text-lg">Movie</h2>
              </CardTitle>
              <CardDescription>
                Into <code>completed/movies</code>, then Radarr moves it into your library.
              </CardDescription>
            </CardHeader>
          </Card>
        </Link>
        <Link to="/download/tv" className="rounded-xl focus-visible:ring-2">
          <Card className="h-full transition-colors hover:border-primary">
            <CardHeader>
              <CardTitle>
                <h2 className="text-lg">TV Show</h2>
              </CardTitle>
              <CardDescription>
                Fill the gaps Sonarr is missing, one episode at a time, then it moves them
                into your library.
              </CardDescription>
            </CardHeader>
          </Card>
        </Link>
      </div>
    </div>
  )
}
