import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { json, mockApi, noContent, renderApp, sentBodies } from '@/test/mockApi'

import type { Preset } from '../types'

const base = {
  'GET /api/auth/me': () => json({ username: 'owner' }),
  'GET /healthz': () => json({ status: 'ok', version: '1.2.3' }),
}

function preset(overrides: Partial<Preset> = {}): Preset {
  return {
    id: 1,
    name: '1080p mkv remux',
    media_type: 'movie',
    options: { quality: '1080p', container: 'mkv' },
    is_default: true,
    ...overrides,
  }
}

const PRESETS: Preset[] = [
  preset(),
  preset({ id: 2, name: 'Phone-friendly mp4', media_type: 'any', is_default: false }),
]

async function row(name: string) {
  return within(await screen.findByRole('region', { name }))
}

describe('PresetsPage', () => {
  it('lists presets with their media type and default badge', async () => {
    mockApi({ ...base, 'GET /api/presets': () => json(PRESETS) })
    renderApp('/presets')

    const first = await row('1080p mkv remux')
    expect(first.getByText('movie')).toBeInTheDocument()
    expect(first.getByText('Default')).toBeInTheDocument()
    expect(first.queryByRole('button', { name: 'Make default' })).not.toBeInTheDocument()

    const second = await row('Phone-friendly mp4')
    expect(second.getByText('any')).toBeInTheDocument()
    expect(second.queryByText('Default')).not.toBeInTheDocument()
    expect(second.getByRole('button', { name: 'Make default' })).toBeInTheDocument()
  })

  it('says so when there are none', async () => {
    mockApi({ ...base, 'GET /api/presets': () => json([]) })
    renderApp('/presets')

    expect(await screen.findByText(/No presets yet/)).toBeInTheDocument()
  })

  it('edits a preset', async () => {
    const fetchMock = mockApi({
      ...base,
      'GET /api/presets': () => json(PRESETS),
      'PATCH /api/presets/1': () => json(preset({ name: 'Renamed' })),
    })
    renderApp('/presets')

    const first = await row('1080p mkv remux')
    fireEvent.click(first.getByRole('button', { name: 'Edit' }))
    fireEvent.change(first.getByLabelText('Name'), { target: { value: 'Renamed' } })
    fireEvent.change(first.getByLabelText('Container'), { target: { value: 'mp4' } })
    fireEvent.change(first.getByLabelText('Media type'), { target: { value: 'tv' } })
    fireEvent.click(first.getByRole('button', { name: 'Save preset' }))

    await waitFor(() => {
      const [body] = sentBodies(fetchMock, 'PATCH /api/presets/1') as {
        name: string
        media_type: string
        options: { container: string; quality: string }
      }[]
      expect(body.name).toBe('Renamed')
      expect(body.media_type).toBe('tv')
      expect(body.options.container).toBe('mp4')
      // The options it already had are kept, not reset to the form's own defaults.
      expect(body.options.quality).toBe('1080p')
    })
  })

  it('sets a default', async () => {
    const fetchMock = mockApi({
      ...base,
      'GET /api/presets': () => json(PRESETS),
      'PATCH /api/presets/2': () => json(preset({ id: 2, is_default: true })),
    })
    renderApp('/presets')

    const second = await row('Phone-friendly mp4')
    fireEvent.click(second.getByRole('button', { name: 'Make default' }))

    await waitFor(() =>
      expect(sentBodies(fetchMock, 'PATCH /api/presets/2')).toEqual([{ is_default: true }]),
    )
  })

  it('deletes a preset', async () => {
    const fetchMock = mockApi({
      ...base,
      'GET /api/presets': () => json(PRESETS),
      'DELETE /api/presets/2': () => noContent(),
    })
    renderApp('/presets')

    const second = await row('Phone-friendly mp4')
    fireEvent.click(second.getByRole('button', { name: 'Delete' }))

    await waitFor(() => expect(sentBodies(fetchMock, 'DELETE /api/presets/2')).toHaveLength(1))
  })

  it('shows why a save failed', async () => {
    mockApi({
      ...base,
      'GET /api/presets': () => json(PRESETS),
      'PATCH /api/presets/1': () => json({ detail: 'that rate limit is not a rate' }, 422),
    })
    renderApp('/presets')

    const first = await row('1080p mkv remux')
    fireEvent.click(first.getByRole('button', { name: 'Edit' }))
    fireEvent.click(first.getByRole('button', { name: 'Save preset' }))

    expect(await first.findByRole('alert')).toHaveTextContent('that rate limit is not a rate')
  })
})
