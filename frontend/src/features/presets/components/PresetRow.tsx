import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { DEFAULT_OPTIONS, DownloadOptionsFields, NativeSelect } from '@/features/requests'
import type { DownloadOptions } from '@/features/requests'

import { deletePreset, presetsQueryKey, updatePreset } from '../api'
import type { Preset, PresetMediaType } from '../types'

const MEDIA_TYPES: { value: PresetMediaType; label: string }[] = [
  { value: 'any', label: 'Any' },
  { value: 'movie', label: 'Movie' },
  { value: 'tv', label: 'TV' },
  { value: 'other', label: 'Other' },
]

/** One saved preset: rename, re-pick its options, make it the default, delete it. */
export default function PresetRow({ preset }: { preset: Preset }) {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(preset.name)
  const [mediaType, setMediaType] = useState<PresetMediaType>(preset.media_type)
  // Spread over the defaults, so a preset saved before an option existed still edits cleanly.
  const [options, setOptions] = useState<DownloadOptions>({
    ...DEFAULT_OPTIONS,
    ...preset.options,
  })
  const refresh = () => queryClient.invalidateQueries({ queryKey: presetsQueryKey })

  const save = useMutation({
    mutationFn: () => updatePreset(preset.id, { name: name.trim(), media_type: mediaType, options }),
    onSuccess: async () => {
      setEditing(false)
      await refresh()
    },
  })
  const makeDefault = useMutation({
    mutationFn: () => updatePreset(preset.id, { is_default: true }),
    onSuccess: refresh,
  })
  const remove = useMutation({
    mutationFn: () => deletePreset(preset.id),
    onSuccess: refresh,
  })
  const failed = save.error ?? makeDefault.error ?? remove.error

  return (
    <Card role="region" aria-label={preset.name}>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="font-semibold">{preset.name}</h2>
          <Badge variant="outline">{preset.media_type}</Badge>
          {preset.is_default && <Badge>Default</Badge>}
          <div className="ml-auto flex gap-2">
            {!preset.is_default && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={makeDefault.isPending}
                onClick={() => makeDefault.mutate()}
              >
                Make default
              </Button>
            )}
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setEditing((open) => !open)}
            >
              {editing ? 'Cancel' : 'Edit'}
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={remove.isPending}
              onClick={() => remove.mutate()}
            >
              Delete
            </Button>
          </div>
        </div>

        {editing && (
          <div className="flex flex-col gap-4">
            <div className="flex flex-wrap gap-4">
              <div className="flex flex-col gap-2">
                <Label htmlFor={`preset-${preset.id}-name`}>Name</Label>
                <Input
                  id={`preset-${preset.id}-name`}
                  className="w-56"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor={`preset-${preset.id}-media-type`}>Media type</Label>
                <NativeSelect
                  id={`preset-${preset.id}-media-type`}
                  value={mediaType}
                  onChange={(e) => setMediaType(e.target.value as PresetMediaType)}
                >
                  {MEDIA_TYPES.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </NativeSelect>
              </div>
            </div>
            {/* No inspection here, so only the options that apply to every video show. */}
            <DownloadOptionsFields value={options} onChange={setOptions} />
            <div>
              <Button
                type="button"
                size="sm"
                disabled={name.trim() === '' || save.isPending}
                onClick={() => save.mutate()}
              >
                Save preset
              </Button>
            </div>
          </div>
        )}

        {failed && (
          <p role="alert" className="text-destructive text-sm">
            {failed.message}
          </p>
        )}
      </CardContent>
    </Card>
  )
}
