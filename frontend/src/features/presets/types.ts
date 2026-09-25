import type { DownloadOptions } from '@/features/requests'

/** A preset belongs to one wizard, or to all of them (`any`). */
export type PresetMediaType = 'movie' | 'tv' | 'other' | 'any'

export type Preset = {
  id: number
  name: string
  media_type: PresetMediaType
  /** Partial, so a preset saved before an option existed still applies over the defaults. */
  options: Partial<DownloadOptions>
  is_default: boolean
}

export type PresetCreate = {
  name: string
  media_type: PresetMediaType
  options: DownloadOptions
  is_default?: boolean
}

export type PresetUpdate = {
  name?: string
  media_type?: PresetMediaType
  options?: DownloadOptions
  is_default?: boolean
}
