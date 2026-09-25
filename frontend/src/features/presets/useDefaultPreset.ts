import { useQuery } from '@tanstack/react-query'
import { useEffect, useEffectEvent, useRef } from 'react'

import { DEFAULT_OPTIONS } from '@/features/requests'
import type { DownloadOptions } from '@/features/requests'

import { listPresets, presetsQueryKey } from './api'
import { defaultPresetFor } from './choose'
import type { PresetMediaType } from './types'

/**
 * Start a wizard from the default preset for its media type, once (requirements §5 step 2d).
 * `enabled` is false for a "download again", whose own options win over any preset.
 */
export function useDefaultPreset(
  mediaType: PresetMediaType,
  apply: (options: DownloadOptions) => void,
  enabled = true,
): void {
  const presets = useQuery({ queryKey: presetsQueryKey, queryFn: listPresets, enabled })
  const applied = useRef(false)
  const onApply = useEffectEvent(apply)

  useEffect(() => {
    if (!enabled || applied.current || !presets.data) return
    applied.current = true
    const preset = defaultPresetFor(presets.data, mediaType)
    // Spread over the defaults, so a preset saved before an option existed still applies.
    if (preset) onApply({ ...DEFAULT_OPTIONS, ...preset.options })
  }, [enabled, presets.data, mediaType])
}
