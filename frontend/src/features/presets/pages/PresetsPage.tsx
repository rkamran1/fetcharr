import { useQuery } from '@tanstack/react-query'

import { listPresets, presetsQueryKey } from '../api'
import PresetRow from '../components/PresetRow'

/** The saved option bundles: edit, set a default, delete (requirements §5 step 2d, §12). */
export default function PresetsPage() {
  const presets = useQuery({ queryKey: presetsQueryKey, queryFn: listPresets })

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Presets</h1>
      <p className="text-muted-foreground text-sm">
        Presets are saved download options. Save one from any wizard, then pick it there to fill
        the form. One preset per media type can be the default the wizard starts with.
      </p>
      {presets.isPending && <p>Loading…</p>}
      {presets.isError && (
        <p role="alert" className="text-destructive text-sm">
          {presets.error.message}
        </p>
      )}
      {presets.data?.length === 0 && (
        <p className="text-muted-foreground text-sm">
          No presets yet. Set up the options you like in a wizard and save them there.
        </p>
      )}
      {presets.data?.map((preset) => <PresetRow key={preset.id} preset={preset} />)}
    </div>
  )
}
