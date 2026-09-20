import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { json, mockApi, noContent, renderApp, sentBodies } from '@/test/mockApi'

const settings = {
  radarr_url: null,
  radarr_api_key_set: false,
  radarr_from_env: false,
  sonarr_url: null,
  sonarr_api_key_set: false,
  sonarr_from_env: false,
}

const base = {
  'GET /api/auth/me': () => json({ username: 'owner' }),
  'GET /healthz': () => json({ status: 'ok', version: '1.2.3' }),
  'GET /api/settings': () => json(settings),
}

function type(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } })
}

/** The page holds one card per arr app, so every query is scoped to one of them. */
function card(name: 'Radarr' | 'Sonarr') {
  return within(screen.getByRole('region', { name }))
}

async function findCard(name: 'Radarr' | 'Sonarr') {
  return within(await screen.findByRole('region', { name }))
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
        json({ ...settings, radarr_url: 'http://radarr:7878', radarr_api_key_set: true }),
      'PATCH /api/settings': () =>
        json({ ...settings, radarr_url: 'http://radarr:7878', radarr_api_key_set: true }),
    })
    renderApp('/settings')

    const radarr = await findCard('Radarr')
    const url = radarr.getByLabelText('Radarr URL')
    await waitFor(() => expect(url).toHaveValue('http://radarr:7878'))
    const apiKey = radarr.getByLabelText('API key')
    expect(apiKey).toHaveValue('')
    expect(apiKey).toHaveAttribute('placeholder', 'Set — type a new key to replace it')

    fireEvent.change(apiKey, { target: { value: 'a-new-key' } })
    fireEvent.click(radarr.getByRole('button', { name: 'Save' }))

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

    fireEvent.click((await findCard('Radarr')).getByRole('button', { name: 'Test' }))

    expect(await screen.findByText('Connected to Radarr 6.4.4.')).toBeInTheDocument()
  })

  it('reports why the connection did not work', async () => {
    mockApi({
      ...base,
      'POST /api/arr/radarr/test': () =>
        json({ ok: false, version: null, error: 'Radarr rejected the API key; check it in Settings' }),
    })
    renderApp('/settings')

    fireEvent.click((await findCard('Radarr')).getByRole('button', { name: 'Test' }))

    expect(await screen.findByRole('status')).toHaveTextContent(
      "Radarr didn't answer: Radarr rejected the API key; check it in Settings",
    )
  })

  it('locks the fields when the environment sets them', async () => {
    mockApi({
      ...base,
      'GET /api/settings': () =>
        json({
          ...settings,
          radarr_url: 'http://env:7878',
          radarr_api_key_set: true,
          radarr_from_env: true,
        }),
    })
    renderApp('/settings')

    const radarr = await findCard('Radarr')
    await waitFor(() => expect(radarr.getByLabelText('Radarr URL')).toBeDisabled())
    expect(radarr.getByLabelText('API key')).toBeDisabled()
    expect(radarr.getByRole('button', { name: 'Save' })).toBeDisabled()
    expect(radarr.getByText(/RADARR_URL and RADARR_API_KEY are set/)).toBeInTheDocument()
    // The Sonarr card is configured on its own, so nothing there is locked.
    expect(card('Sonarr').getByLabelText('Sonarr URL')).toBeEnabled()
  })
})

describe('Sonarr settings (AC1)', () => {
  it('saves the Sonarr URL and key, and never shows the stored key', async () => {
    const fetchMock = mockApi({
      ...base,
      'PATCH /api/settings': () =>
        json({ ...settings, sonarr_url: 'http://sonarr:8989', sonarr_api_key_set: true }),
    })
    renderApp('/settings')

    const sonarr = await findCard('Sonarr')
    fireEvent.change(sonarr.getByLabelText('Sonarr URL'), {
      target: { value: 'http://sonarr:8989' },
    })
    const apiKey = sonarr.getByLabelText('API key')
    expect(apiKey).toHaveAttribute('placeholder', 'Not set')
    fireEvent.change(apiKey, { target: { value: 'sonarr-key' } })
    fireEvent.click(sonarr.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(sentBodies(fetchMock, 'PATCH /api/settings')).toEqual([
        { sonarr_url: 'http://sonarr:8989', sonarr_api_key: 'sonarr-key' },
      ]),
    )
    // The saved key never comes back, only "set".
    await waitFor(() => expect(sonarr.getByLabelText('API key')).toHaveValue(''))
  })

  it('tests the Sonarr connection and reports the version', async () => {
    mockApi({
      ...base,
      'POST /api/arr/sonarr/test': () => json({ ok: true, version: '4.0.20', error: null }),
    })
    renderApp('/settings')

    fireEvent.click((await findCard('Sonarr')).getByRole('button', { name: 'Test' }))

    expect(await screen.findByText('Connected to Sonarr 4.0.20.')).toBeInTheDocument()
  })

  it('reports why Sonarr did not answer', async () => {
    mockApi({
      ...base,
      'POST /api/arr/sonarr/test': () =>
        json({ ok: false, version: null, error: 'Sonarr rejected the API key' }),
    })
    renderApp('/settings')

    fireEvent.click((await findCard('Sonarr')).getByRole('button', { name: 'Test' }))

    expect(await screen.findByRole('status')).toHaveTextContent(
      "Sonarr didn't answer: Sonarr rejected the API key",
    )
  })

  it('locks the Sonarr fields when the environment sets them', async () => {
    mockApi({
      ...base,
      'GET /api/settings': () =>
        json({
          ...settings,
          sonarr_url: 'http://env:8989',
          sonarr_api_key_set: true,
          sonarr_from_env: true,
        }),
    })
    renderApp('/settings')

    const sonarr = await findCard('Sonarr')
    await waitFor(() => expect(sonarr.getByLabelText('Sonarr URL')).toBeDisabled())
    expect(sonarr.getByLabelText('API key')).toBeDisabled()
    expect(sonarr.getByRole('button', { name: 'Save' })).toBeDisabled()
    expect(sonarr.getByText(/SONARR_URL and SONARR_API_KEY are set/)).toBeInTheDocument()
  })
})
