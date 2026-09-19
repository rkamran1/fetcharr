import { useMutation } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'

import { inspect } from '@/api/client'
import InspectCard from '@/components/InspectCard'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

/** Temporary page for step 1 (inspect); the download wizard replaces it in M5a. */
export default function InspectPage() {
  const [url, setUrl] = useState('')
  const mutation = useMutation({ mutationFn: inspect })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    mutation.mutate(url.trim())
  }

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Inspect</h1>
      <form className="flex flex-col gap-2 sm:flex-row sm:items-end" onSubmit={submit}>
        <div className="flex flex-1 flex-col gap-2">
          <Label htmlFor="url">Video URL</Label>
          <Input
            id="url"
            type="url"
            inputMode="url"
            placeholder="https://www.youtube.com/watch?v=…"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            required
          />
        </div>
        <Button type="submit" disabled={mutation.isPending}>
          Inspect
        </Button>
      </form>
      {!mutation.isIdle && (
        <InspectCard isPending={mutation.isPending} error={mutation.error} data={mutation.data} />
      )}
    </div>
  )
}
