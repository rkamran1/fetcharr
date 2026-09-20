import { fireEvent, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { json, mockApi, noContent, renderApp, sentBodies } from '@/test/mockApi'

const settings = { radarr_url: null, radarr_api_key_set: false, radarr_from_env: false }

const base = {
  'GET /api/auth/me': () => json({ username: 'owner' }),
  'GET /healthz': () => json({ status: 'ok', version: '1.2.3' }),
  'GET /api/settings': () => json(settings),
}

function type(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } })
}

async function fillPasswordForm(current: string) {
  await screen.findByRole('heading', { name: 'Change password' })
  type('Current password', current)
  type('New password', 'a new password')
  type('Repeat new password', 'a new password')
  fireEvent.click(screen.getByRole('button', { name: 'Change password' }))
}

describe('SettingsPage', () => {
  it('changes the password', async () => {
    const fetchMock = mockApi({ ...base, 'POST /api/auth/password': noContent })
    renderApp('/settings')

    await fillPasswordForm('old password')

    expect(await screen.findByRole('status')).toHaveTextContent('Password changed.')
    expect(sentBodies(fetchMock, 'POST /api/auth/password')).toEqual([
      { current_password: 'old password', new_password: 'a new password' },
    ])
    expect(screen.getByLabelText('Current password')).toHaveValue('')
  })

  it('shows an error for a wrong current password', async () => {
    mockApi({
      ...base,
      'POST /api/auth/password': () => json({ detail: 'Current password is incorrect' }, 400),
    })
    renderApp('/settings')

    await fillPasswordForm('wrong password')

    expect(await screen.findByRole('alert')).toHaveTextContent('Current password is incorrect')
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('regenerates the API key and shows it once with copy', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    mockApi({ ...base, 'POST /api/auth/api-key': () => json({ api_key: 'k3y-once' }) })
    renderApp('/settings')

    fireEvent.click(await screen.findByRole('button', { name: 'Regenerate API key' }))

    expect(await screen.findByDisplayValue('k3y-once')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Copy' }))
    expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument()
    expect(writeText).toHaveBeenCalledWith('k3y-once')

    fireEvent.click(screen.getByRole('link', { name: 'Home' }))
    await screen.findByRole('heading', { name: 'Home' })
    fireEvent.click(screen.getByRole('link', { name: 'Settings' }))
    await screen.findByRole('heading', { name: 'API key' })
    expect(screen.queryByDisplayValue('k3y-once')).not.toBeInTheDocument()
  })
})

describe('Radarr settings', () => {
  it('saves the connection and never shows the stored key', async () => {
    const fetchMock = mockApi({
      ...base,
      'GET /api/settings': () =>
        json({ radarr_url: 'http://radarr:7878', radarr_api_key_set: true, radarr_from_env: false }),
      'PATCH /api/settings': () =>
        json({ radarr_url: 'http://radarr:7878', radarr_api_key_set: true, radarr_from_env: false }),
    })
    renderApp('/settings')

    const url = await screen.findByLabelText('Radarr URL')
    await waitFor(() => expect(url).toHaveValue('http://radarr:7878'))
    const apiKey = screen.getByLabelText('API key')
    expect(apiKey).toHaveValue('')
    expect(apiKey).toHaveAttribute('placeholder', 'Set — type a new key to replace it')

    type('API key', 'a-new-key')
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(sentBodies(fetchMock, 'PATCH /api/settings')).toEqual([
        { radarr_url: 'http://radarr:7878', radarr_api_key: 'a-new-key' },
      ]),
    )
  })

  it('tests the connection and reports the version', async () => {
    mockApi({
      ...base,
      'POST /api/arr/radarr/test': () => json({ ok: true, version: '6.4.4', error: null }),
    })
    renderApp('/settings')

    fireEvent.click(await screen.findByRole('button', { name: 'Test' }))

    expect(await screen.findByText('Connected to Radarr 6.4.4.')).toBeInTheDocument()
  })

  it('reports why the connection did not work', async () => {
    mockApi({
      ...base,
      'POST /api/arr/radarr/test': () =>
        json({ ok: false, version: null, error: 'Radarr rejected the API key; check it in Settings' }),
    })
    renderApp('/settings')

    fireEvent.click(await screen.findByRole('button', { name: 'Test' }))

    expect(await screen.findByRole('status')).toHaveTextContent(
      "Radarr didn't answer: Radarr rejected the API key; check it in Settings",
    )
  })

  it('locks the fields when the environment sets them', async () => {
    mockApi({
      ...base,
      'GET /api/settings': () =>
        json({ radarr_url: 'http://env:7878', radarr_api_key_set: true, radarr_from_env: true }),
    })
    renderApp('/settings')

    const url = await screen.findByLabelText('Radarr URL')
    await waitFor(() => expect(url).toBeDisabled())
    expect(screen.getByLabelText('API key')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
    expect(screen.getByText(/RADARR_URL and RADARR_API_KEY are set/)).toBeInTheDocument()
  })
})
