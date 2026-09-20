import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { formatBytes } from '@/lib/format'

import NativeSelect from './NativeSelect'
import type { Container, DownloadOptions, Quality } from '../types'

const QUALITIES: Quality[] = ['144p', '240p', '360p', '480p', '720p', '1080p', '1440p', '2160p']
const FRAGMENTS = ['auto', '1', '2', '4', '8'] as const
const ARIA2C = ['auto', 'on', 'off'] as const

type Props = {
  value: DownloadOptions
  onChange: (next: DownloadOptions) => void
  /** The heights this video really has (requirements §5 step 2d). */
  heights: number[]
  estimatedSizes: Record<string, number>
}

/** The download options shared by every wizard (requirements §5 step 2d). */
export default function DownloadOptionsFields({
  value,
  onChange,
  heights,
  estimatedSizes,
}: Props) {
  const set = <K extends keyof DownloadOptions>(key: K, next: DownloadOptions[K]) =>
    onChange({ ...value, [key]: next })

  // Coerced because a height can arrive as a string, and de-duplicated.
  const available = [...new Set(heights.map(Number))].filter(
    (height) => Number.isFinite(height) && height > 0,
  )
  const tallest = available.length > 0 ? Math.max(...available) : 0

  // Roughly what a download will cost: a reported filesize, or the bitrate over the
  // running time, plus the audio track (§5 step 1). Always approximate, so say so.
  const sizeOf = (height: number): string =>
    estimatedSizes[String(height)] ? ` · ≈ ${formatBytes(estimatedSizes[String(height)])}` : ''

  // A quality is a ceiling ("at most this height"), so each one really downloads the
  // tallest format at or below it. Offer a step only when it picks a format nothing
  // else already picks, and name the height it will actually get, so a video with
  // unusual heights still shows real formats and real sizes.
  const picked = new Set<number>()
  const options: { value: Quality; label: string }[] = []
  for (const quality of QUALITIES) {
    const ceiling = Number.parseInt(quality)
    const effective = Math.max(0, ...available.filter((height) => height <= ceiling))
    if (effective === 0 || picked.has(effective)) continue
    picked.add(effective)
    options.push({
      value: quality,
      label: `${quality}${effective === ceiling ? '' : ` → ${effective}p`}${sizeOf(effective)}`,
    })
  }
  options.reverse()

  // Name what "best" will actually download, so the collapsed control says something.
  const bestLabel =
    tallest > 0 ? `Best available (${tallest}p${sizeOf(tallest)})` : 'Best available'

  const fragments = value.fragments === 'auto' ? 'auto' : String(value.fragments)
  const aria2c = value.use_aria2c === 'auto' ? 'auto' : value.use_aria2c ? 'on' : 'off'

  return (
    <>
      <div className="flex flex-col gap-4 sm:flex-row">
        <div className="flex flex-col gap-2">
          <Label htmlFor="quality">Quality</Label>
          <NativeSelect
            id="quality"
            value={value.quality}
            onChange={(e) => set('quality', e.target.value as Quality)}
          >
            <option value="best">{bestLabel}</option>
            {options.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </NativeSelect>
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="container">Container</Label>
          <NativeSelect
            id="container"
            value={value.container}
            onChange={(e) => set('container', e.target.value as Container)}
          >
            <option value="mkv">mkv</option>
            <option value="mp4">mp4</option>
          </NativeSelect>
        </div>
      </div>

      <details className="text-sm">
        <summary className="cursor-pointer">Advanced</summary>
        <div className="flex flex-col gap-4 pt-4 sm:flex-row">
          <div className="flex flex-col gap-2">
            <Label htmlFor="fragments">Fragments</Label>
            <NativeSelect
              id="fragments"
              value={fragments}
              onChange={(e) =>
                set('fragments', e.target.value === 'auto' ? 'auto' : Number(e.target.value))
              }
            >
              {FRAGMENTS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </NativeSelect>
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="aria2c">aria2c</Label>
            <NativeSelect
              id="aria2c"
              value={aria2c}
              onChange={(e) =>
                set('use_aria2c', e.target.value === 'auto' ? 'auto' : e.target.value === 'on')
              }
            >
              {ARIA2C.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </NativeSelect>
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="retries">Retries</Label>
            <Input
              id="retries"
              type="number"
              min={0}
              max={20}
              className="w-24"
              value={value.retries}
              onChange={(e) => set('retries', Number(e.target.value))}
            />
          </div>
        </div>
      </details>
    </>
  )
}
