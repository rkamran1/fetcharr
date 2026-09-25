import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useId, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { DEFAULT_OPTIONS, NativeSelect } from '@/features/requests'
import type { DownloadOptions } from '@/features/requests'

import { createPreset, listPresets, presetsQueryKey } from '../api'
import { presetsFor } from '../choose'
import type { PresetMediaType } from '../types'

type Props = {
  mediaType: PresetMediaType
  /** What "Save as preset" stores: the options the wizard is showing right now. */
  options: DownloadOptions
  onApply: (options: DownloadOptions) => void
}

/** Pick a saved option bundle, or save the current one (requirements §5 step 2d). */
export default function PresetSelector({ mediaType, options, onApply }: Props) {
  const id = useId()
  const queryClient = useQueryClient()
  const [picked, setPicked] = useState('')
  const [name, setName] = useState('')

  const presets = useQuery({ queryKey: presetsQueryKey, queryFn: listPresets })
  const available = presetsFor(presets.data ?? [], mediaType)

  const save = useMutation({
    mutationFn: () => createPreset({ name: name.trim(), media_type: mediaType, options }),
    onSuccess: (preset) => {
      setName('')
      setPicked(String(preset.id))
      return queryClient.invalidateQueries({ queryKey: presetsQueryKey })
    },
  })

  const apply = (value: string) => {
    setPicked(value)
    const preset = available.find((candidate) => String(candidate.id) === value)
    // Spread over the defaults, so a preset saved before an option existed still applies.
    if (preset) onApply({ ...DEFAULT_OPTIONS, ...preset.options })
  }

  return (
    <div className="flex flex-col gap-3">
      {available.length > 0 && (
        <div className="flex flex-col gap-2">
          <Label htmlFor={`${id}-preset`}>Preset</Label>
          <NativeSelect id={`${id}-preset`} value={picked} onChange={(e) => apply(e.target.value)}>
            <option value="">No preset</option>
            {available.map((preset) => (
              <option key={preset.id} value={preset.id}>
                {preset.name}
                {preset.is_default ? ' (default)' : ''}
              </option>
            ))}
          </NativeSelect>
        </div>
      )}
      <div className="flex items-end gap-2">
        <div className="flex flex-col gap-2">
          <Label htmlFor={`${id}-preset-name`}>Save as preset</Label>
          <Input
            id={`${id}-preset-name`}
            className="w-56"
            placeholder="e.g. 1080p mkv remux"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={name.trim() === '' || save.isPending}
          onClick={() => save.mutate()}
        >
          Save
        </Button>
      </div>
      {save.isError && (
        <p role="alert" className="text-destructive text-sm">
          {save.error.message}
        </p>
      )}
    </div>
  )
}
