import { useEffect, useState, useSyncExternalStore } from 'react'

/** Tailwind's `md` breakpoint: a table from here up, cards below (§12). */
const DESKTOP = '(min-width: 768px)'

function desktopQuery(): MediaQueryList | null {
  return typeof window.matchMedia === 'function' ? window.matchMedia(DESKTOP) : null
}

/** True on a desktop-width screen; false (mobile first) where there's no `matchMedia`. */
export function useIsDesktop(): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const query = desktopQuery()
      query?.addEventListener('change', onChange)
      return () => query?.removeEventListener('change', onChange)
    },
    () => desktopQuery()?.matches ?? false,
  )
}

/** `value`, once it has stopped changing for `delay` ms: one search per pause in typing. */
export function useDebounced<T>(value: T, delay: number): T {
  const [settled, setSettled] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])
  return settled
}
