import { fireEvent, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { json, mockApi, noContent, renderApp, sentBodies } from '@/test/mockApi'

const base = {
  'GET /api/auth/me': () => json({ username: 'owner' }),
  'GET /healthz': () => json({ status: 'ok', version: '1.2.3' }),
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
