import type { Preset, PresetMediaType } from './types'

/** What one wizard may offer: its own presets plus the `any` ones (§5 step 2d). */
export function presetsFor(presets: Preset[], mediaType: PresetMediaType): Preset[] {
  return presets.filter(
    (preset) => preset.media_type === mediaType || preset.media_type === 'any',
  )
}

/** The preset a wizard starts with: its own type's default, else the `any` default. */
export function defaultPresetFor(
  presets: Preset[],
  mediaType: PresetMediaType,
): Preset | undefined {
  const defaults = presetsFor(presets, mediaType).filter((preset) => preset.is_default)
  return defaults.find((preset) => preset.media_type === mediaType) ?? defaults[0]
}
