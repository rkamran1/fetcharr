import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

/** The yt-dlp FAQ's advice on exporting cookies, as §8 asks the UI to show it. */
export default function CookieHelp() {
  return (
    <Card role="region" aria-label="How to export cookies">
      <CardHeader>
        <CardTitle>
          <h2>How to export cookies</h2>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="text-muted-foreground flex list-disc flex-col gap-2 pl-5 text-sm">
          <li>
            Sign in inside a <strong>private/incognito window</strong>, export the cookies as a
            Netscape <code>cookies.txt</code> with a browser extension, then{' '}
            <strong>close that window</strong>. Using the same session in a normal window rotates
            the cookies and invalidates the export.
          </li>
          <li>
            Use a <strong>throwaway account</strong>: downloading with cookies can get an account
            flagged.
          </li>
          <li>
            Only this site's cookies are kept from the file; the rest of a browser export is
            dropped.
          </li>
          <li>
            <code>--cookies-from-browser</code> isn't possible here: there is no browser inside the
            container.
          </li>
        </ul>
      </CardContent>
    </Card>
  )
}
