import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { testHardwareEncode } from '@/features/system'

import { getSettings, settingsQueryKey, updateSettings } from '../api'

/** The three profiles, and what their quality number means; the scales are not the same. */
const PROFILES = [
  { key: 'hevc-qsv', name: 'HEVC Intel QSV', scale: 'global_quality' },
  { key: 'hevc-vaapi', name: 'HEVC VAAPI', scale: 'global_quality' },
  { key: 'x265-software', name: 'x265 software', scale: 'CRF' },
]

/** The default quality per transcode profile, plus the hardware self-test (§4.1, §13.1). */
export default function TranscodeSettings() {
  const queryClient = useQueryClient()
  const settings = useQuery({ queryKey: settingsQueryKey, queryFn: getSettings })
  const [edited, setEdited] = useState<Record<string, number>>({})

  const test = useMutation({ mutationFn: testHardwareEncode })
  const save = useMutation({
    mutationFn: updateSettings,
    onSuccess: (data) => {
      queryClient.setQueryData(settingsQueryKey, data)
      setEdited({})
    },
  })

  const stored = settings.data?.transcode_quality ?? {}
  const valueOf = (key: string) => edited[key] ?? stored[key] ?? ''

  const submit = (event: FormEvent) => {
    event.preventDefault()
    save.mutate({ transcode_quality: { ...stored, ...edited } })
  }

  const report = test.data

  return (
    <Card role="region" aria-label="Transcoding">
      <CardHeader>
        <CardTitle>
          <h2>Transcoding</h2>
        </CardTitle>
        <CardDescription>
          The quality a download uses when you pick that profile. Downloads never transcode
          unless you choose a profile for them.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <form className="flex flex-col gap-4" onSubmit={submit}>
          <div className="flex flex-col gap-4 sm:flex-row">
            {PROFILES.map((profile) => (
              <div key={profile.key} className="flex flex-col gap-2">
                <Label htmlFor={`quality-${profile.key}`}>
                  {profile.name} ({profile.scale})
                </Label>
                <Input
                  id={`quality-${profile.key}`}
                  type="number"
                  min={1}
                  max={51}
                  className="w-40"
                  value={valueOf(profile.key)}
                  onChange={(e) =>
                    setEdited((current) => ({
                      ...current,
                      [profile.key]: Number(e.target.value),
                    }))
                  }
                />
              </div>
            ))}
          </div>
          {save.isError && (
            <p role="alert" className="text-destructive text-sm">
              {save.error.message}
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            <Button type="submit" disabled={save.isPending}>
              Save
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => test.mutate()}
              disabled={test.isPending}
            >
              Test hardware encode
            </Button>
          </div>
        </form>
        {save.isSuccess && (
          <p role="status" className="text-sm">
            Transcode defaults saved.
          </p>
        )}
        {test.isError && (
          <p role="alert" className="text-destructive text-sm">
            {test.error.message}
          </p>
        )}
        {report && (
          <div className="flex flex-col gap-1 text-sm">
            <p role="status">{report.message}</p>
            {report.profiles.map((profile) => (
              <p key={profile.profile} className="text-muted-foreground">
                {profile.profile}: {profile.ok ? 'works' : (profile.error ?? 'failed')}
              </p>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
