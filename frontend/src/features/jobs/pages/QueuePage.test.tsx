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
  media_type: 'other',
  request_title: 'Big Buck Bunny',
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
  transcode_fallback_used: false,
  season: null,
  episode: null,
  episode_title: null,
  air_date: null,
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

// ------------------------------------------------ M6 AC9/AC12: a TV request

/** One episode of a three-episode TV request (§12). */
function episodeJob(number: number, overrides: Partial<Job> = {}): Job {
  return {
    ...job,
    id: `tv-${number}`,
    request_id: 'req-tv',
    media_type: 'tv',
    request_title: 'Some Show',
    source_title: `Some Show Ep ${number}`,
    season: 1,
    episode: number,
    episode_title: `Episode ${number}`,
    import_status: 'pending',
    ...overrides,
  }
}

describe('a TV request in the queue (AC12)', () => {
  it('groups the episodes under the series and season with a done count', async () => {
    mockApi({
      ...base,
      'GET /api/jobs': () =>
        json({
          jobs: [
            episodeJob(2),
            episodeJob(1, { status: 'completed', progress_pct: 100, import_status: 'imported' }),
            episodeJob(3),
          ],
        }),
    })
    mockEventSource()
    renderApp('/queue')

    const group = await screen.findByRole('region', { name: 'Some Show · Season 1' })
    const headings = within(group).getAllByRole('heading', { level: 2 })
    // One episode of three has finished (§12).
    expect(headings[0]).toHaveTextContent('Some Show · Season 11/3')
    // Episode order inside the request, however the list arrived (§6.1).
    expect(headings.slice(1).map((heading) => heading.textContent)).toEqual([
      'S01E01 — Episode 1',
      'S01E02 — Episode 2',
      'S01E03 — Episode 3',
    ])
  })

  it('shows each episode its own progress and import badge', async () => {
    mockApi({
      ...base,
      'GET /api/jobs': () =>
        json({
          jobs: [
            episodeJob(1, {
              status: 'completed',
              import_status: 'imported',
              imported_path: '/library/tv-shows/Some Show/Season 1/Some Show - S01E01.mkv',
            }),
            episodeJob(2, { status: 'downloading', progress_pct: 42 }),
          ],
        }),
    })
    mockEventSource()
    renderApp('/queue')

    expect(await screen.findByText('✅ Imported')).toBeInTheDocument()
    expect(
      screen.getByText('/library/tv-shows/Some Show/Season 1/Some Show - S01E01.mkv'),
    ).toBeInTheDocument()
    // Only the running episode has a progress bar, and it is its own.
    const bars = screen.getAllByRole('progressbar')
    expect(bars).toHaveLength(1)
    expect(bars[0]).toHaveAttribute('aria-valuenow', '42')
  })

  it("shows Sonarr's rejection reasons and retries the import (AC9)", async () => {
    const rejected = episodeJob(2, {
      status: 'completed',
      import_status: 'not_imported',
      completed_path: '/web-downloads/completed/tv-shows/Some Show/Season 1/ep2.mkv',
      import_detail: {
        rejections: ['Not an upgrade for existing episode file(s)', 'Sample'],
      },
    })
    const fetchMock = mockApi({
      ...base,
      'GET /api/jobs': () => json({ jobs: [rejected] }),
      'POST /api/jobs/tv-2/import': () => json({ ...rejected, import_status: 'pending' }),
    })
    mockEventSource()
    renderApp('/queue')

    expect(await screen.findByText('⚠ Not imported')).toBeInTheDocument()
    // Sonarr's words, under Sonarr's name: a TV job never went to Radarr (§7.5).
    const reasons = within(screen.getByRole('list', { name: "Sonarr's reasons" })).getAllByRole(
      'listitem',
    )
    expect(reasons.map((item) => item.textContent)).toEqual([
      'Not an upgrade for existing episode file(s)',
      'Sample',
    ])
    expect(screen.getByText(/Import manually: open Sonarr/)).toHaveTextContent(
      rejected.completed_path!,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Retry import' }))

    await waitFor(() => expect(sentBodies(fetchMock, 'POST /api/jobs/tv-2/import')).toHaveLength(1))
  })

  it('leaves a single-job request without a group heading', async () => {
    mockQueue()
    mockEventSource()
    renderApp('/queue')

    await screen.findByText('Big Buck Bunny')
    expect(screen.queryByRole('heading', { level: 2, name: /\d\/\d/ })).not.toBeInTheDocument()
  })
})

describe('QueuePage transcoding', () => {
  const transcoding: Job = {
    ...job,
    status: 'transcoding',
    phase: 'transcode',
    progress_pct: 42,
    // A transcode has no download speed or ETA to show.
    speed_bps: null,
    eta_s: null,
    downloaded_bytes: null,
  }

  it('shows the transcode percent while transcoding', async () => {
    mockQueue([transcoding])
    mockEventSource()
    renderApp('/queue')

    expect(await screen.findByText('Transcoding')).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: 'Progress' })).toHaveAttribute(
      'aria-valuenow',
      '42',
    )
  })

  it('follows the transcode percent from the event stream', async () => {
    mockQueue([transcoding])
    const source = mockEventSource()
    renderApp('/queue')
    await screen.findByText('Transcoding')

    source.last?.emit('job.progress', {
      job_id: 'job-1',
      progress_pct: 80,
      downloaded_bytes: null,
      total_bytes: null,
      speed_bps: null,
      eta_s: null,
    })

    await waitFor(() =>
      expect(screen.getByRole('progressbar', { name: 'Progress' })).toHaveAttribute(
        'aria-valuenow',
        '80',
      ),
    )
  })

  it('notes when a job fell back to software', async () => {
    mockQueue([{ ...finished, transcode_fallback_used: true }])
    mockEventSource()
    renderApp('/queue')

    expect(await screen.findByText(/fell back to software/i)).toBeInTheDocument()
  })

  it('says nothing about the fallback when it did not happen', async () => {
    mockQueue([finished])
    mockEventSource()
    renderApp('/queue')

    await screen.findByText('Completed')
    expect(screen.queryByText(/fell back to software/i)).not.toBeInTheDocument()
  })
})

describe('QueuePage import rejections (AC16)', () => {
  const explanation =
    'the file is 2:05 long but Jumper runs 88 min, so Radarr takes it for a sample or trailer, ' +
    'not the movie itself. Pick the full-length video, or download clips and trailers as Other.'

  it("explains a sample rejection under Radarr's reason", async () => {
    mockQueue([
      {
        ...finished,
        import_status: 'not_imported',
        import_detail: { rejections: ['Sample'], explanation },
      },
    ])
    mockEventSource()
    renderApp('/queue')

    expect(await screen.findByText('⚠ Not imported')).toBeInTheDocument()
    // Radarr's own word stays, verbatim, with what it means for this file next to it.
    const reasons = within(screen.getByRole('list', { name: "Radarr's reasons" })).getAllByRole(
      'listitem',
    )
    expect(reasons.map((item) => item.textContent)).toEqual(['Sample'])
    expect(screen.getByText(explanation)).toBeInTheDocument()
  })

  it('adds nothing when the reason needs no explaining', async () => {
    mockQueue([
      {
        ...finished,
        import_status: 'not_imported',
        import_detail: { rejections: ['Not an upgrade for existing movie file(s)'] },
      },
    ])
    mockEventSource()
    renderApp('/queue')

    expect(await screen.findByText('⚠ Not imported')).toBeInTheDocument()
    expect(screen.queryByText(/takes it for a sample/)).not.toBeInTheDocument()
  })
})
