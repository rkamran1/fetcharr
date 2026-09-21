import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

import { createSite, sitesQueryKey } from '../api'

/** A site the built-in list doesn't know: a key plus its domains (§8). */
export default function AddSiteForm() {
  const queryClient = useQueryClient()
  const [key, setKey] = useState('')
  const [domains, setDomains] = useState('')

  const add = useMutation({
    mutationFn: createSite,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: sitesQueryKey })
      setKey('')
      setDomains('')
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    add.mutate({
      key: key.trim(),
      domains: domains.split(/[\s,]+/).filter(Boolean),
    })
  }

  return (
    <Card role="region" aria-label="Add site">
      <CardHeader>
        <CardTitle>
          <h2>Add site</h2>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <form className="flex max-w-sm flex-col gap-4" onSubmit={submit}>
          <div className="flex flex-col gap-2">
            <Label htmlFor="site-key">Key</Label>
            <Input
              id="site-key"
              placeholder="vimeo"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              required
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="site-domains">Domains</Label>
            <Input
              id="site-domains"
              placeholder="vimeo.com, vimeocdn.com"
              value={domains}
              onChange={(e) => setDomains(e.target.value)}
              required
            />
          </div>
          {add.isError && (
            <p role="alert" className="text-destructive text-sm">
              {add.error.message}
            </p>
          )}
          <Button type="submit" className="self-start" disabled={add.isPending}>
            Add site
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}
