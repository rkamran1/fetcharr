import { useQuery } from '@tanstack/react-query'
import { useEffect, useEffectEvent, useMemo, useRef } from 'react'
import { useSearchParams } from 'react-router'

import type { Job } from '@/features/jobs'

import { getRequest, requestQueryKey } from './api'
import { DEFAULT_OPTIONS } from './types'
import type { DownloadOptions, RequestRead } from './types'

/** What "download again" hands a wizard: the old request, the job, and its options (§12). */
export type Prefill = {
  request: RequestRead
  job: Job
  options: DownloadOptions
}

/**
 * The wizard that downloads this job again, with the request and job in the URL so the
 * page can be reloaded. A TV job opens its series, where the episode row is filled in.
 */
export function againPath(request: RequestRead, job: Job): string {
  const params = new URLSearchParams({ again: request.id, job: job.id }).toString()
  if (request.media_type === 'tv' && request.sonarr_series_id !== null) {
    return `/download/tv/${request.sonarr_series_id}?${params}`
  }
  if (request.media_type === 'movie') return `/download/movie?${params}`
  return `/download/other?${params}`
}

/** The prefill named by `?again=<request>&job=<job>`, once the request has loaded. */
export function useDownloadAgain(): Prefill | null {
  const [params] = useSearchParams()
  const requestId = params.get('again')
  const jobId = params.get('job')
  const request = useQuery({
    queryKey: requestQueryKey(requestId ?? ''),
    queryFn: () => getRequest(requestId!),
    enabled: requestId !== null,
  })

  return useMemo(() => {
    const data = request.data
    const job = data?.jobs.find((candidate) => candidate.id === jobId) ?? data?.jobs[0]
    if (!data || !job) return null
    // An older request lacks the fields added since; they fall back to the defaults.
    return { request: data, job, options: { ...DEFAULT_OPTIONS, ...data.options } }
  }, [request.data, jobId])
}

/**
 * Whether this wizard was opened by "download again". Unlike `useDownloadAgain`, it answers
 * on the first render, before the request has loaded: a default preset must not overwrite
 * options that are still on their way.
 */
export function useIsDownloadAgain(): boolean {
  const [params] = useSearchParams()
  return params.get('again') !== null
}

/** Apply a prefill once per job, however often the page renders afterwards. */
export function usePrefill(prefill: Prefill | null, apply: (prefill: Prefill) => void): void {
  const applied = useRef<string | null>(null)
  const onPrefill = useEffectEvent(apply)
  useEffect(() => {
    if (prefill && applied.current !== prefill.job.id) {
      applied.current = prefill.job.id
      onPrefill(prefill)
    }
  }, [prefill])
}
