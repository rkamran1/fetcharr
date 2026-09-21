import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

import { sitesQueryKey, uploadCookies } from '../api'
import type { Site } from '../types'

type Props = {
  site: Site
  /** Called with the server's warning (or null) once the upload has been answered. */
  onDone: (warning: string | null) => void
}

/** A cookies.txt, chosen as a file or pasted; either way the text is what gets sent (§8). */
export default function UploadCookies({ site, onDone }: Props) {
  const queryClient = useQueryClient()
  const [file, setFile] = useState<File | null>(null)
  const [pasted, setPasted] = useState('')

  const upload = useMutation({
    mutationFn: async () => uploadCookies(site.key, file ? await file.text() : pasted),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: sitesQueryKey })
      onDone(data.warning)
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    upload.mutate()
  }

  return (
    <form className="flex flex-col gap-3" onSubmit={submit}>
      <div className="flex flex-col gap-2">
        <Label htmlFor={`${site.key}-file`}>Cookies file</Label>
        <Input
          id={`${site.key}-file`}
          type="file"
          accept=".txt,text/plain"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
      </div>
      <div className="flex flex-col gap-2">
        <Label htmlFor={`${site.key}-paste`}>Or paste cookies.txt</Label>
        <textarea
          id={`${site.key}-paste`}
          className="border-input min-h-24 rounded-md border bg-transparent px-3 py-2 font-mono text-xs"
          placeholder="# Netscape HTTP Cookie File"
          spellCheck={false}
          value={pasted}
          onChange={(e) => setPasted(e.target.value)}
        />
      </div>
      {upload.isError && (
        <p role="alert" className="text-destructive text-sm">
          {upload.error.message}
        </p>
      )}
      <Button
        type="submit"
        className="self-start"
        disabled={upload.isPending || (!file && !pasted.trim())}
      >
        Save cookies
      </Button>
    </form>
  )
}
