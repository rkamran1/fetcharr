import { request } from '@/api/client'

import type { Job, JobList, JobLog } from './types'

export const jobsQueryKey = ['jobs'] as const
export const jobLogQueryKey = (id: string) => ['jobs', id, 'log'] as const

export const listJobs = () => request<JobList>('GET', '/api/jobs')
export const getJobLog = (id: string) => request<JobLog>('GET', `/api/jobs/${id}/log`)
export const cancelJob = (id: string) => request<Job>('POST', `/api/jobs/${id}/cancel`)
export const retryJob = (id: string) => request<Job>('POST', `/api/jobs/${id}/retry`)
export const retryImport = (id: string) => request<Job>('POST', `/api/jobs/${id}/import`)
export const deleteJob = (id: string, deleteFile = false) =>
  request<void>('DELETE', `/api/jobs/${id}?delete_file=${deleteFile}`)
