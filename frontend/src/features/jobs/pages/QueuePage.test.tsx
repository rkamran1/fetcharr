import { fireEvent, screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { Job } from '@/features/jobs'
import { json, mockApi, mockEventSource, renderApp } from '@/test/mockApi'

const base = {
  'GET /api/auth/me': () => json({ username: 'owner' }),
  'GET /healthz': () => json({ status: 'ok', version: '1.2.3' }),
}

const job: Job = {
  id: 'job-1',
  request_id: 'req-1',
  url: 'https://www.youtube.com/watch?v=aqz-KE-bpKQ',
  source_title: 'Big Buck Bunny',
  thumbnail_url: null,
  duration: 635,
  status: 'downloading',
  phase: 'download',
  attempt: 1,
  progress_pct: 10,
  downloaded_bytes: 1048576,
  total_bytes: 10485760,
  speed_bps: 524288,
  eta_s: 18,
  completed_path: null,
  file_size: null,
  import_status: 'n/a',
  error_code: null,
  error_message: null,
  created_at: '2026-09-20T10:00:00',
  started_at: '2026-09-20T10:00:01',
  finished_at: null,
}

function mockQueue(jobs: Job[] = [job]) {
  return mockApi({
    ...base,
    'GET /api/jobs': () => json({ jobs }),
    'GET /api/jobs/job-1/log': () =>
      json({ lines: [{ ts: '2026-09-20T10:00:02', level: 'info', line: '[download] 10.0%' }] }),
    'POST /api/jobs/job-1/cancel': () => json({ ...job, status: 'cancelled' }),
  })
}

describe('QueuePage', () => {
  it('renders a job with its progress, speed and phase chip', async () => {
    mockQueue()
    mockEventSource()
    renderApp('/queue')

    expect(await screen.findByRole('heading', { name: 'Big Buck Bunny' })).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: 'Progress' })).toHaveAttribute(
      'aria-valuenow',
      '10',
    )
    expect(screen.getByText(/512 KB\/s/)).toBeInTheDocument()
    expect(screen.getByText(/ETA 0:18/)).toBeInTheDocument()
    expect(screen.getByText('Downloading')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument()
  })

  it('applies SSE progress and state events', async () => {
    mockQueue()
    const eventSource = mockEventSource()
    renderApp('/queue')
    await screen.findByRole('heading', { name: 'Big Buck Bunny' })

    eventSource.last!.emit('job.progress', {
      job_id: 'job-1',
      progress_pct: 63.5,
      downloaded_bytes: 6658457,
      total_bytes: 10485760,
      speed_bps: 1048576,
      eta_s: 4,
    })

    await waitFor(() =>
      expect(screen.getByRole('progressbar', { name: 'Progress' })).toHaveAttribute(
        'aria-valuenow',
        '64',
      ),
    )
    expect(screen.getByText(/1\.0 MB\/s/)).toBeInTheDocument()

    eventSource.last!.emit('job.state', {
      job_id: 'job-1',
      status: 'postprocessing',
      phase: 'download',
    })

    expect(await screen.findByText('Merging')).toBeInTheDocument()
  })

  it('hides Cancel once the job is organizing', async () => {
    mockQueue()
    const eventSource = mockEventSource()
    renderApp('/queue')
    await screen.findByRole('button', { name: 'Cancel' })

    eventSource.last!.emit('job.state', {
      job_id: 'job-1',
      status: 'organizing',
      phase: 'organize',
    })

    expect(await screen.findByText('Moving')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Cancel' })).not.toBeInTheDocument()
  })

  it('shows a finished job as done, not as still downloading', async () => {
    // A completed row keeps the last progress sample it was written with (§3.1 rule 5).
    mockQueue([
      {
        ...job,
        status: 'completed',
        phase: null,
        progress_pct: 100,
        speed_bps: null,
        eta_s: null,
        downloaded_bytes: 16384,
        total_bytes: 3040870,
        file_size: 3040870,
        completed_path: '/web-downloads/completed/other/Big Buck Bunny [aqz].mkv',
        finished_at: '2026-09-20T10:01:00',
      },
    ])
    mockEventSource()
    renderApp('/queue')

    expect(await screen.findByText('Completed')).toBeInTheDocument()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
    expect(screen.queryByText(/ETA/)).not.toBeInTheDocument()
    expect(screen.queryByText(/MB\/s/)).not.toBeInTheDocument()
    expect(screen.queryByText(/16 KB/)).not.toBeInTheDocument()
    // What it produced, and where.
    expect(screen.getByText('2.9 MB')).toBeInTheDocument()
    expect(
      screen.getByText('/web-downloads/completed/other/Big Buck Bunny [aqz].mkv'),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Cancel' })).not.toBeInTheDocument()
  })

  it('opens the log drawer', async () => {
    mockQueue()
    mockEventSource()
    renderApp('/queue')

    fireEvent.click(await screen.findByRole('button', { name: 'Log' }))

    const log = await screen.findByRole('region', { name: 'Log' })
    await waitFor(() => expect(log).toHaveTextContent('[download] 10.0%'))
  })
})
