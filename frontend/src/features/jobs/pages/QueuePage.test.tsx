import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { Job } from '@/features/jobs'
import { json, mockApi, mockEventSource, renderApp, sentBodies } from '@/test/mockApi'

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
  import_attempts: 0,
  import_detail: null,
  imported_path: null,
  imported_at: null,
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
    'POST /api/jobs/job-1/import': () => json({ ...job, import_status: 'pending' }),
  })
}

const finished: Job = {
  ...job,
  status: 'completed',
  phase: null,
  progress_pct: 100,
  speed_bps: null,
  eta_s: null,
  file_size: 3040870,
  completed_path:
    '/web-downloads/completed/movies/Big Buck Bunny (2008)/Big Buck Bunny (2008) WEBDL-1080p.mkv',
  finished_at: '2026-09-20T10:01:00',
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

  it('shows the library path of an imported job', async () => {
    mockQueue([
      {
        ...finished,
        import_status: 'imported',
        imported_path: '/movies/Big Buck Bunny (2008)/Big Buck Bunny (2008) WEBDL-1080p.mkv',
        imported_at: '2026-09-20T10:01:30',
      },
    ])
    mockEventSource()
    renderApp('/queue')

    expect(await screen.findByText('✅ Imported')).toBeInTheDocument()
    expect(
      screen.getByText('/movies/Big Buck Bunny (2008)/Big Buck Bunny (2008) WEBDL-1080p.mkv'),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Retry import' })).not.toBeInTheDocument()
  })

  it("shows Radarr's reasons and offers Retry import", async () => {
    const fetchMock = mockQueue([
      {
        ...finished,
        import_status: 'not_imported',
        import_detail: {
          rejections: ['Not an upgrade for existing movie file(s)', 'Unknown movie'],
        },
      },
    ])
    mockEventSource()
    renderApp('/queue')

    expect(await screen.findByText('⚠ Not imported')).toBeInTheDocument()
    const reasons = within(screen.getByRole('list', { name: "Radarr's reasons" })).getAllByRole(
      'listitem',
    )
    expect(reasons.map((item) => item.textContent)).toEqual([
      'Not an upgrade for existing movie file(s)',
      'Unknown movie',
    ])
    expect(screen.getByText(/Import manually: open Radarr/)).toHaveTextContent(
      finished.completed_path!,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Retry import' }))

    await waitFor(() =>
      expect(sentBodies(fetchMock, 'POST /api/jobs/job-1/import')).toHaveLength(1),
    )
  })

  it('shows an import error with the hint, and applies the job.import event', async () => {
    mockQueue([
      {
        ...finished,
        import_status: 'error',
        import_attempts: 1,
        import_detail: {
          error: 'Radarr rejected the API key; check it in Settings',
          hint: 'check the API key in Settings',
        },
      },
    ])
    const eventSource = mockEventSource()
    renderApp('/queue')

    expect(await screen.findByText('❌ Import error')).toBeInTheDocument()
    expect(screen.getByText('check the API key in Settings')).toBeInTheDocument()

    eventSource.last!.emit('job.import', {
      job_id: 'job-1',
      import_status: 'imported',
      imported_path: '/movies/Big Buck Bunny (2008)/file.mkv',
      import_detail: null,
    })

    expect(await screen.findByText('✅ Imported')).toBeInTheDocument()
    expect(screen.getByText('/movies/Big Buck Bunny (2008)/file.mkv')).toBeInTheDocument()
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
