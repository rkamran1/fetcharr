import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent } from 'react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { NativeSelect } from '@/features/requests'

import { getSettings, previewNaming, settingsQueryKey, updateSettings } from '../api'
import type { ColonMode, NamingTemplates } from '../types'

/** The eight §7.2 templates, in the order Radarr and Sonarr present them. */
const TEMPLATES: { key: keyof NamingTemplates; label: string }[] = [
  { key: 'movie_folder', label: 'Movie folder' },
  { key: 'movie_file', label: 'Movie file' },
  { key: 'series_folder', label: 'Series folder' },
  { key: 'season_folder', label: 'Season folder' },
  { key: 'specials_folder', label: 'Specials folder' },
  { key: 'standard_episode', label: 'Standard episode' },
  { key: 'daily_episode', label: 'Daily episode' },
  { key: 'other', label: 'Other file' },
]

const COLON_MODES: { key: ColonMode; label: string }[] = [
  { key: 'smart', label: 'Smart replace (Title: Sub → Title - Sub)' },
  { key: 'delete', label: 'Delete' },
  { key: 'dash', label: 'Dash' },
  { key: 'space_dash', label: 'Space dash' },
  { key: 'space_dash_space', label: 'Space dash space' },
]

/** The examples, in the order they are shown; each covers a different template. */
const EXAMPLES: { key: string; label: string }[] = [
  { key: 'movie', label: 'Movie' },
  { key: 'episode', label: 'Episode' },
  { key: 'specials', label: 'Special' },
  { key: 'daily', label: 'Daily episode' },
  { key: 'other', label: 'Other' },
]

const TOKENS =
  '{Movie Title} {Release Year} {Series Title} {season} {season:00} {episode:00} ' +
  '{Episode Title} {Air-Date} {Quality Full} {Title} {Id}'

/**
 * The naming templates and the colon replacement mode (§7.2), with a live example
 * rendered by the same functions that name the real files. Changes apply to new
 * downloads only: a request keeps the naming it was created with.
 */
export default function NamingSettings() {
  const queryClient = useQueryClient()
  const settings = useQuery({ queryKey: settingsQueryKey, queryFn: getSettings })
  const [edited, setEdited] = useState<Partial<NamingTemplates>>({})
  const [colon, setColon] = useState<ColonMode | null>(null)

  const stored = settings.data?.naming_templates
  const storedColon = settings.data?.colon_mode
  const templates = { ...stored, ...edited } as Partial<NamingTemplates>
  const colonMode = colon ?? storedColon

  const preview = useMutation({ mutationFn: previewNaming })
  const save = useMutation({
    mutationFn: updateSettings,
    onSuccess: (data) => {
      queryClient.setQueryData(settingsQueryKey, data)
      setEdited({})
      setColon(null)
    },
  })

  // The example follows what the form holds, so an edit shows its effect straight away.
  const { mutate: renderPreview } = preview
  useEffect(() => {
    if (!stored || !colonMode) return
    renderPreview({ templates, colon_mode: colonMode })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [renderPreview, stored, JSON.stringify(templates), colonMode])

  const submit = (event: FormEvent) => {
    event.preventDefault()
    save.mutate({ naming_templates: edited, ...(colon ? { colon_mode: colon } : {}) })
  }

  const reset = () => {
    setEdited({})
    setColon(null)
    save.mutate({ naming_templates: {}, colon_mode: 'smart' })
  }

  return (
    <Card role="region" aria-label="Naming">
      <CardHeader>
        <CardTitle>
          <h2>Naming</h2>
        </CardTitle>
        <CardDescription>
          How finished files are named, so Radarr and Sonarr recognise them. Changes apply to
          new downloads; anything already queued keeps the naming it started with.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <form className="flex flex-col gap-4" onSubmit={submit}>
          <div className="grid gap-4 sm:grid-cols-2">
            {TEMPLATES.map(({ key, label }) => (
              <div key={key} className="flex flex-col gap-2">
                <Label htmlFor={`template-${key}`}>{label}</Label>
                <Input
                  id={`template-${key}`}
                  value={templates[key] ?? ''}
                  onChange={(e) => setEdited((current) => ({ ...current, [key]: e.target.value }))}
                />
                {preview.data?.errors[key] && (
                  <p role="alert" className="text-destructive text-sm">
                    {preview.data.errors[key]}
                  </p>
                )}
              </div>
            ))}
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="colon-mode">Colon replacement</Label>
            <NativeSelect
              id="colon-mode"
              className="sm:w-96"
              value={colonMode ?? 'smart'}
              onChange={(e) => setColon(e.target.value as ColonMode)}
            >
              {COLON_MODES.map((mode) => (
                <option key={mode.key} value={mode.key}>
                  {mode.label}
                </option>
              ))}
            </NativeSelect>
          </div>
          <div>
            <h3 className="text-sm font-medium">Example</h3>
            <dl className="mt-2 flex flex-col gap-1 text-sm">
              {EXAMPLES.map(({ key, label }) => (
                <div key={key} className="flex flex-col sm:flex-row sm:gap-2">
                  <dt className="text-muted-foreground w-32 shrink-0">{label}</dt>
                  <dd className="font-mono break-all">{preview.data?.examples[key] ?? '…'}</dd>
                </div>
              ))}
            </dl>
          </div>
          <p className="text-muted-foreground text-sm">Tokens: {TOKENS}</p>
          {save.isError && (
            <p role="alert" className="text-destructive text-sm">
              {save.error.message}
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            <Button type="submit" disabled={save.isPending}>
              Save
            </Button>
            <Button type="button" variant="outline" onClick={reset} disabled={save.isPending}>
              Reset to Radarr/Sonarr defaults
            </Button>
          </div>
        </form>
        {save.isSuccess && (
          <p role="status" className="text-sm">
            Naming saved.
          </p>
        )}
      </CardContent>
    </Card>
  )
}
