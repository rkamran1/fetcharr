import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'

import type { InspectResult } from '../types'
import InspectCard from './InspectCard'

const result: InspectResult = {
  inspection_id: 7,
  site_key: 'youtube',
  title: 'Big Buck Bunny',
  uploader: 'Blender',
  thumbnail: null,
  duration: 635,
  webpage_url: 'https://www.youtube.com/watch?v=aqz-KE-bpKQ',
  extractor: 'youtube',
  id: 'aqz-KE-bpKQ',
  upload_date: '20141110',
  release_year: 2014,
  video_heights: [1080],
  video_codecs: ['avc1'],
  audio_tracks: [],
  has_hdr: false,
  subtitles: {},
  automatic_captions: {},
  estimated_sizes: {},
  stream_type: 'dash',
  auto: { fragments: 4, use_aria2c: false },
  previous_downloads: [],
}

function renderCard(data: InspectResult) {
  return render(
    <MemoryRouter>
      <InspectCard isPending={false} error={null} data={data} />
    </MemoryRouter>,
  )
}

describe('InspectCard', () => {
  it('notes previous downloads', () => {
    renderCard({
      ...result,
      previous_downloads: [
        {
          job_id: 'job-2',
          created_at: '2026-09-05T10:00:00',
          media_type: 'other',
          path: '/web-downloads/completed/other/Big Buck Bunny [aqz-KE-bpKQ].mkv',
          import_status: 'n/a',
        },
        {
          job_id: 'job-1',
          created_at: '2026-09-01T10:00:00',
          media_type: 'movie',
          path: '/movies/Big Buck Bunny (2008)/Big Buck Bunny (2008) WEBDL-1080p.mkv',
          import_status: 'imported',
        },
      ],
    })

    const note = screen.getByRole('region', { name: 'Downloaded before' })
    const items = within(note).getAllByRole('listitem')
    expect(items.map((item) => item.textContent)).toEqual([
      '2026-09-05 · Other · /web-downloads/completed/other/Big Buck Bunny [aqz-KE-bpKQ].mkv',
      '2026-09-01 · Movie · /movies/Big Buck Bunny (2008)/Big Buck Bunny (2008) WEBDL-1080p.mkv · imported',
    ])
  })

  it('says nothing when there are none', () => {
    renderCard(result)

    expect(screen.getByRole('heading', { name: 'Big Buck Bunny' })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Downloaded before' })).not.toBeInTheDocument()
    expect(screen.queryByText(/Downloaded before/)).not.toBeInTheDocument()
  })
})
