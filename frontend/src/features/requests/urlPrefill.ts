import { useCallback, useEffect, useEffectEvent, useRef } from 'react'
import { useSearchParams } from 'react-router'

/**
 * A URL shared into fetcharr (§12's `share_target`). The chooser at `/share` sends it on to
 * a wizard as `?url=`, which fills its URL field with it. Unlike "download again" it carries
 * no options, so a default preset still applies.
 */
export function useSharedUrl(): string | null {
  const [params] = useSearchParams()
  const url = params.get('url')?.trim()
  return url ? url : null
}

/** Fill a wizard's single URL field from `?url=`, once however often the page renders. */
export function useSharedUrlPrefill(apply: (url: string) => void): void {
  const shared = useSharedUrl()
  const applied = useRef(false)
  const onShared = useEffectEvent(apply)
  useEffect(() => {
    if (shared && !applied.current) {
      applied.current = true
      onShared(shared)
    }
  }, [shared])
}

/**
 * The shared URL, handed out only once. The series page has a URL field per episode, and a
 * link shared from a phone is one episode, so the first row opened claims it and the rest
 * start empty.
 */
export function useTakeSharedUrl(): () => string | null {
  const shared = useSharedUrl()
  const taken = useRef(false)
  return useCallback(() => {
    if (taken.current) return null
    taken.current = true
    return shared
  }, [shared])
}

/** Claim the shared URL for this row, if it is still going, and fill the field with it. */
export function useClaimedUrlPrefill(
  take: (() => string | null) | null | undefined,
  apply: (url: string) => void,
): void {
  const claimed = useRef(false)
  const onClaimed = useEffectEvent(apply)
  useEffect(() => {
    if (claimed.current || !take) return
    claimed.current = true
    const url = take()
    if (url) onClaimed(url)
  }, [take])
}

/** The wizard a shared URL opens for this type, with the URL carried along. */
export function sharePath(mediaType: 'movie' | 'tv' | 'other', url: string): string {
  const query = `?${new URLSearchParams({ url }).toString()}`
  if (mediaType === 'movie') return `/download/movie${query}`
  if (mediaType === 'tv') return `/download/tv${query}`
  return `/download/other${query}`
}
