import { useQuery } from '@tanstack/react-query'
import { useId } from 'react'

import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import type { ImportStatus, JobStatus } from '@/features/jobs'
import { NativeSelect, type MediaType, type RequestFilters } from '@/features/requests'
import { listSites, sitesQueryKey } from '@/features/sites'

/** The filters the bar sets; the search box and the page live beside it. */
export type Filters = Pick<
  RequestFilters,
  'type' | 'status' | 'import_status' | 'site' | 'from' | 'to'
>

const TYPES: [MediaType, string][] = [
  ['movie', 'Movie'],
  ['tv', 'TV'],
  ['other', 'Other'],
]

const STATUSES: [JobStatus, string][] = [
  ['completed', 'Completed'],
  ['failed', 'Failed'],
  ['cancelled', 'Cancelled'],
  ['queued', 'Queued'],
  ['downloading', 'Downloading'],
  ['transcoding', 'Transcoding'],
  ['importing', 'Importing'],
]

const IMPORT_STATUSES: [ImportStatus, string][] = [
  ['imported', 'Imported'],
  ['not_imported', 'Not imported'],
  ['error', 'Import error'],
  ['pending', 'Pending'],
  ['n/a', 'Not applicable'],
]

type Props = {
  value: Filters
  onChange: (filters: Filters) => void
}

/** Type, status, import status, site and date range (§12), each "any" until picked. */
export default function HistoryFilters({ value, onChange }: Props) {
  const id = useId()
  const sites = useQuery({ queryKey: sitesQueryKey, queryFn: listSites })
  const set = (key: keyof Filters, next: string) =>
    onChange({ ...value, [key]: next === '' ? undefined : next })

  const select = (key: keyof Filters, label: string, options: [string, string][]) => (
    <div className="flex flex-col gap-1">
      <Label htmlFor={`${id}-${key}`}>{label}</Label>
      <NativeSelect
        id={`${id}-${key}`}
        value={value[key] ?? ''}
        onChange={(event) => set(key, event.target.value)}
      >
        <option value="">Any</option>
        {options.map(([option, text]) => (
          <option key={option} value={option}>
            {text}
          </option>
        ))}
      </NativeSelect>
    </div>
  )

  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
      {select('type', 'Type', TYPES)}
      {select('status', 'Status', STATUSES)}
      {select('import_status', 'Import', IMPORT_STATUSES)}
      {select(
        'site',
        'Site',
        (sites.data ?? []).map((site): [string, string] => [site.key, site.label]),
      )}
      <div className="flex flex-col gap-1">
        <Label htmlFor={`${id}-from`}>From</Label>
        <Input
          id={`${id}-from`}
          type="date"
          value={value.from ?? ''}
          onChange={(event) => set('from', event.target.value)}
        />
      </div>
      <div className="flex flex-col gap-1">
        <Label htmlFor={`${id}-to`}>To</Label>
        <Input
          id={`${id}-to`}
          type="date"
          value={value.to ?? ''}
          onChange={(event) => set('to', event.target.value)}
        />
      </div>
    </div>
  )
}
