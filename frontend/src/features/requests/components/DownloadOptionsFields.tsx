import { useId } from 'react'

import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { formatBytes } from '@/lib/format'

import NativeSelect from './NativeSelect'
import type {
  Container,
  DownloadOptions,
  Quality,
  SponsorBlockMode,
  SubtitleMode,
  TranscodeProfile,
  VideoCodec,
} from '../types'

const QUALITIES: Quality[] = ['144p', '240p', '360p', '480p', '720p', '1080p', '1440p', '2160p']
const FRAGMENTS = ['auto', '1', '2', '4', '8'] as const
const ARIA2C = ['auto', 'on', 'off'] as const

// Off first and selected by default: a download only ever transcodes because it was asked
// to (§5 step 2d). `hevc-qsv` is the default *profile* once transcoding is picked (§4.1).
const TRANSCODES: { value: TranscodeProfile; label: string }[] = [
  { value: 'off', label: 'Off (remux only)' },
  { value: 'hevc-qsv', label: 'HEVC Intel QSV' },
  { value: 'hevc-vaapi', label: 'HEVC VAAPI' },
  { value: 'x265-software', label: 'x265 software' },
]

const CODECS: { value: VideoCodec; label: string }[] = [
  { value: 'any', label: 'Any' },
  { value: 'h264', label: 'H.264' },
  { value: 'vp9', label: 'VP9' },
  { value: 'av1', label: 'AV1' },
]

const SUBTITLE_MODES: { value: SubtitleMode; label: string }[] = [
  { value: 'off', label: 'Off' },
  { value: 'embed', label: 'Embed in the video' },
  { value: 'sidecar', label: 'Sidecar .srt' },
]

const SPONSORBLOCK_MODES: { value: SponsorBlockMode; label: string }[] = [
  { value: 'off', label: 'Off' },
  { value: 'mark', label: 'Mark as chapters' },
  { value: 'remove', label: 'Remove the segments' },
]

type Props = {
  value: DownloadOptions
  onChange: (next: DownloadOptions) => void
  /** The heights this video really has (requirements §5 step 2d). */
  heights?: number[]
  estimatedSizes?: Record<string, number>
  /** From the inspection: a group is only shown when this video really has it (§5 step 1). */
  subtitles?: Record<string, string[]>
  automaticCaptions?: Record<string, string[]>
  audioTracks?: { lang: string | null }[]
  hasHdr?: boolean
}

/** The download options shared by every wizard (requirements §5 step 2d). */
export default function DownloadOptionsFields({
  value,
  onChange,
  heights = [],
  estimatedSizes = {},
  subtitles = {},
  automaticCaptions = {},
  audioTracks = [],
  hasHdr = false,
}: Props) {
  // Unique per instance: a TV season shows one of these per episode, and duplicate ids
  // would point every label at the first row's control.
  const id = useId()
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

  // The languages this video really offers, manual subtitles first (§5 step 1).
  const subtitleLanguages = [
    ...new Set([...Object.keys(subtitles), ...Object.keys(automaticCaptions)]),
  ].sort()
  const hasAutoCaptions = Object.keys(automaticCaptions).length > 0
  // Only worth a control when there is something to choose between.
  const audioLanguages = [
    ...new Set(audioTracks.map((track) => track.lang).filter((lang) => lang !== null)),
  ].sort()

  const toggleLanguage = (language: string, on: boolean) => {
    const next = on
      ? [...value.subtitles.languages, language]
      : value.subtitles.languages.filter((picked) => picked !== language)
    set('subtitles', { ...value.subtitles, languages: next })
  }

  const fragments = value.fragments === 'auto' ? 'auto' : String(value.fragments)
  const aria2c = value.use_aria2c === 'auto' ? 'auto' : value.use_aria2c ? 'on' : 'off'

  return (
    <>
      <div className="flex flex-col gap-4 sm:flex-row">
        <div className="flex flex-col gap-2">
          <Label htmlFor={`${id}-quality`}>Quality</Label>
          <NativeSelect
            id={`${id}-quality`}
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
          <Label htmlFor={`${id}-container`}>Container</Label>
          <NativeSelect
            id={`${id}-container`}
            value={value.container}
            onChange={(e) => set('container', e.target.value as Container)}
          >
            <option value="mkv">mkv</option>
            <option value="mp4">mp4</option>
          </NativeSelect>
        </div>
      </div>

      {subtitleLanguages.length > 0 && (
        <fieldset className="flex flex-col gap-3">
          <legend className="text-sm font-medium">Subtitles</legend>
          <div className="flex flex-col gap-2">
            <Label htmlFor={`${id}-subtitle-mode`}>Subtitles</Label>
            <NativeSelect
              id={`${id}-subtitle-mode`}
              value={value.subtitles.mode}
              onChange={(e) =>
                set('subtitles', { ...value.subtitles, mode: e.target.value as SubtitleMode })
              }
            >
              {SUBTITLE_MODES.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </NativeSelect>
          </div>
          {value.subtitles.mode !== 'off' && (
            <>
              <div className="flex flex-wrap gap-x-4 gap-y-2">
                {subtitleLanguages.map((language) => (
                  <label key={language} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={value.subtitles.languages.includes(language)}
                      onChange={(e) => toggleLanguage(language, e.target.checked)}
                    />
                    {language}
                  </label>
                ))}
              </div>
              {hasAutoCaptions && (
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={value.subtitles.include_auto_captions}
                    onChange={(e) =>
                      set('subtitles', {
                        ...value.subtitles,
                        include_auto_captions: e.target.checked,
                      })
                    }
                  />
                  Include auto-captions
                </label>
              )}
            </>
          )}
        </fieldset>
      )}

      {audioLanguages.length > 1 && (
        <div className="flex flex-col gap-2">
          <Label htmlFor={`${id}-audio-language`}>Audio track</Label>
          <NativeSelect
            id={`${id}-audio-language`}
            value={value.audio_language ?? ''}
            onChange={(e) => set('audio_language', e.target.value === '' ? null : e.target.value)}
          >
            <option value="">Best available</option>
            {audioLanguages.map((language) => (
              <option key={language} value={language}>
                {language}
              </option>
            ))}
          </NativeSelect>
        </div>
      )}

      <details className="text-sm">
        <summary className="cursor-pointer">Advanced</summary>
        <div className="flex flex-col gap-4 pt-4 sm:flex-row">
          <div className="flex flex-col gap-2">
            <Label htmlFor={`${id}-video-codec`}>Video codec</Label>
            <NativeSelect
              id={`${id}-video-codec`}
              value={value.video_codec}
              onChange={(e) => set('video_codec', e.target.value as VideoCodec)}
            >
              {CODECS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </NativeSelect>
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor={`${id}-sponsorblock`}>SponsorBlock</Label>
            <NativeSelect
              id={`${id}-sponsorblock`}
              value={value.sponsorblock.mode}
              onChange={(e) =>
                set('sponsorblock', {
                  ...value.sponsorblock,
                  mode: e.target.value as SponsorBlockMode,
                })
              }
            >
              {SPONSORBLOCK_MODES.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </NativeSelect>
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor={`${id}-rate-limit`}>Rate limit</Label>
            <Input
              id={`${id}-rate-limit`}
              className="w-32"
              placeholder="e.g. 5M"
              value={value.rate_limit ?? ''}
              onChange={(e) => set('rate_limit', e.target.value === '' ? null : e.target.value)}
            />
          </div>
        </div>
        {hasHdr && (
          <div className="pt-4">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={value.allow_hdr}
                onChange={(e) => set('allow_hdr', e.target.checked)}
              />
              Allow HDR
            </label>
          </div>
        )}
        <div className="flex flex-col gap-4 pt-4 sm:flex-row">
          <div className="flex flex-col gap-2">
            <Label htmlFor={`${id}-fragments`}>Fragments</Label>
            <NativeSelect
              id={`${id}-fragments`}
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
            <Label htmlFor={`${id}-aria2c`}>aria2c</Label>
            <NativeSelect
              id={`${id}-aria2c`}
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
            <Label htmlFor={`${id}-retries`}>Retries</Label>
            <Input
              id={`${id}-retries`}
              type="number"
              min={0}
              max={20}
              className="w-24"
              value={value.retries}
              onChange={(e) => set('retries', Number(e.target.value))}
            />
          </div>
        </div>
        <div className="flex flex-col gap-4 pt-4 sm:flex-row">
          <div className="flex flex-col gap-2">
            <Label htmlFor={`${id}-transcode`}>Transcode</Label>
            <NativeSelect
              id={`${id}-transcode`}
              value={value.transcode}
              onChange={(e) => set('transcode', e.target.value as TranscodeProfile)}
            >
              {TRANSCODES.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </NativeSelect>
          </div>
          {/* The quality only means something once a profile is picked, and its scale
              depends on which one, so it is hidden until then. */}
          {value.transcode !== 'off' && (
            <div className="flex flex-col gap-2">
              <Label htmlFor={`${id}-transcode-quality`}>Transcode quality</Label>
              <Input
                id={`${id}-transcode-quality`}
                type="number"
                min={1}
                max={51}
                className="w-40"
                placeholder="Settings default"
                value={value.transcode_quality ?? ''}
                onChange={(e) =>
                  set('transcode_quality', e.target.value === '' ? null : Number(e.target.value))
                }
              />
            </div>
          )}
        </div>
      </details>
    </>
  )
}
