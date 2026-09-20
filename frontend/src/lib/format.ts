const UNITS = ['B', 'KB', 'MB', 'GB', 'TB']

/** A byte count for people: `512 KB`, `1.3 GB`. */
export function formatBytes(bytes: number): string {
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value < 10 && unit > 0 ? value.toFixed(1) : Math.round(value)} ${UNITS[unit]}`
}
