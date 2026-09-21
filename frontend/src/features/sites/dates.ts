const DAY_MS = 24 * 60 * 60 * 1000

/** The backend sends naive UTC (`2026-09-21T12:00:00`); read it as UTC, not local time. */
export function parseUtc(value: string): Date {
  return new Date(/[zZ]|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`)
}

/** Whole days from now until `value`, rounded up; negative once it has passed. */
export function daysUntil(value: string, now: Date = new Date()): number {
  return Math.ceil((parseUtc(value).getTime() - now.getTime()) / DAY_MS)
}

/** `2026-09-21`: short, and the same in every locale and time zone. */
export function formatDay(value: string): string {
  return parseUtc(value).toISOString().slice(0, 10)
}
