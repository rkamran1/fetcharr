import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { json, mockApi, noContent, renderApp, sentBodies } from '@/test/mockApi'

import type { Site } from '../types'

const base = {
  'GET /api/auth/me': () => json({ username: 'owner' }),
  'GET /healthz': () => json({ status: 'ok', version: '1.2.3' }),
}

const COOKIES = '# Netscape HTTP Cookie File\n\n.youtube.com\tTRUE\t/\tTRUE\t4102444800\tSID\tx\n'

function site(overrides: Partial<Site>): Site {
  return {
    key: 'youtube',
    label: 'YouTube',
    domains: ['youtube.com', 'youtu.be'],
    builtin: true,
    status: 'none',
    cookie_count: null,
    earliest_expiry: null,
    last_used_at: null,
    uploaded_at: null,
    ...overrides,
  }
}

const SITES: Site[] = [
  site({ key: 'bilibili', label: 'Bilibili', domains: ['bilibili.com'] }),
  site({
    status: 'expiring',
    cookie_count: 14,
    earliest_expiry: '2026-10-01T00:00:00',
    last_used_at: '2026-09-20T08:30:00',
    uploaded_at: '2026-09-01T10:00:00',
  }),
  site({
    key: 'dailymotion',
    label: 'Dailymotion',
    domains: ['dailymotion.com'],
    status: 'flagged',
    cookie_count: 3,
  }),
  site({
    key: 'vimeo',
    label: 'vimeo',
    domains: ['vimeo.com'],
    builtin: false,
    status: 'expired',
    cookie_count: 1,
    earliest_expiry: '2026-01-01T00:00:00',
  }),
]

async function row(label: string) {
  return within(await screen.findByRole('region', { name: label }))
}

describe('CookiesPage', () => {
  it('shows one row per site with its status badge', async () => {
    mockApi({ ...base, 'GET /api/sites': () => json(SITES) })
    renderApp('/cookies')

    const youtube = await row('YouTube')
    expect(youtube.getByText('Expiring')).toBeInTheDocument()
    expect(youtube.getByText('14')).toBeInTheDocument()
    expect(youtube.getByText('2026-10-01')).toBeInTheDocument()
    expect(youtube.getByText('2026-09-20')).toBeInTheDocument()
    expect(youtube.getByRole('button', { name: 'Replace' })).toBeInTheDocument()
    expect(youtube.queryByRole('button', { name: 'Delete site' })).not.toBeInTheDocument()

    const bilibili = await row('Bilibili')
    expect(bilibili.getByText('No cookies')).toBeInTheDocument()
    expect(bilibili.getByRole('button', { name: 'Upload' })).toBeInTheDocument()
    expect(bilibili.queryByRole('button', { name: 'Delete cookies' })).not.toBeInTheDocument()

    expect((await row('Dailymotion')).getByText('Possibly invalid')).toBeInTheDocument()
    const vimeo = await row('vimeo')
    expect(vimeo.getByText('Expired')).toBeInTheDocument()
    expect(vimeo.getByRole('button', { name: 'Delete site' })).toBeInTheDocument()
  })

  it('uploads a file', async () => {
    const fetchMock = mockApi({
      ...base,
      'GET /api/sites': () => json(SITES),
      'PUT /api/sites/bilibili/cookies': () => json({ site: SITES[0], warning: null }),
    })
    renderApp('/cookies')

    const bilibili = await row('Bilibili')
    fireEvent.click(bilibili.getByRole('button', { name: 'Upload' }))
    const file = new File([COOKIES], 'cookies.txt', { type: 'text/plain' })
    fireEvent.change(bilibili.getByLabelText('Cookies file'), {
      target: { files: [file] },
    })
    fireEvent.click(bilibili.getByRole('button', { name: 'Save cookies' }))

    await waitFor(() =>
      expect(sentBodies(fetchMock, 'PUT /api/sites/bilibili/cookies')).toEqual([{ text: COOKIES }]),
    )
    await waitFor(() =>
      expect(bilibili.queryByRole('button', { name: 'Save cookies' })).not.toBeInTheDocument(),
    )
  })

  it('uploads pasted text', async () => {
    const fetchMock = mockApi({
      ...base,
      'GET /api/sites': () => json(SITES),
      'PUT /api/sites/youtube/cookies': () => json({ site: SITES[1], warning: null }),
    })
    renderApp('/cookies')

    const youtube = await row('YouTube')
    fireEvent.click(youtube.getByRole('button', { name: 'Replace' }))
    fireEvent.change(youtube.getByLabelText('Or paste cookies.txt'), {
      target: { value: COOKIES },
    })
    fireEvent.click(youtube.getByRole('button', { name: 'Save cookies' }))

    await waitFor(() =>
      expect(sentBodies(fetchMock, 'PUT /api/sites/youtube/cookies')).toEqual([{ text: COOKIES }]),
    )
  })

  it('shows the upload warning', async () => {
    mockApi({
      ...base,
      'GET /api/sites': () => json(SITES),
      'PUT /api/sites/youtube/cookies': () =>
        json({
          site: SITES[1],
          warning: 'None of these cookies belong to youtube.com, so nothing was saved.',
        }),
    })
    renderApp('/cookies')

    const youtube = await row('YouTube')
    fireEvent.click(youtube.getByRole('button', { name: 'Replace' }))
    fireEvent.change(youtube.getByLabelText('Or paste cookies.txt'), {
      target: { value: COOKIES },
    })
    fireEvent.click(youtube.getByRole('button', { name: 'Save cookies' }))

    expect(await youtube.findByRole('status')).toHaveTextContent('nothing was saved')
  })

  it('shows a validation error', async () => {
    mockApi({
      ...base,
      'GET /api/sites': () => json(SITES),
      'PUT /api/sites/youtube/cookies': () =>
        json({ detail: 'line 3: expected 7 tab-separated fields' }, 422),
    })
    renderApp('/cookies')

    const youtube = await row('YouTube')
    fireEvent.click(youtube.getByRole('button', { name: 'Replace' }))
    fireEvent.change(youtube.getByLabelText('Or paste cookies.txt'), {
      target: { value: 'nope' },
    })
    fireEvent.click(youtube.getByRole('button', { name: 'Save cookies' }))

    expect(await youtube.findByRole('alert')).toHaveTextContent(
      'line 3: expected 7 tab-separated fields',
    )
  })

  it('adds a custom site', async () => {
    const fetchMock = mockApi({
      ...base,
      'GET /api/sites': () => json(SITES),
      'POST /api/sites': () => json(SITES[3], 201),
    })
    renderApp('/cookies')

    const form = await row('Add site')
    fireEvent.change(form.getByLabelText('Key'), {
      target: { value: 'vimeo' },
    })
    fireEvent.change(form.getByLabelText('Domains'), {
      target: { value: 'vimeo.com, vimeocdn.com' },
    })
    fireEvent.click(form.getByRole('button', { name: 'Add site' }))

    await waitFor(() =>
      expect(sentBodies(fetchMock, 'POST /api/sites')).toEqual([
        { key: 'vimeo', domains: ['vimeo.com', 'vimeocdn.com'] },
      ]),
    )
    await waitFor(() => expect(form.getByLabelText('Key')).toHaveValue(''))
  })

  it('deletes cookies and custom sites', async () => {
    const fetchMock = mockApi({
      ...base,
      'GET /api/sites': () => json(SITES),
      'DELETE /api/sites/youtube/cookies': noContent,
      'DELETE /api/sites/vimeo': noContent,
    })
    renderApp('/cookies')

    fireEvent.click((await row('YouTube')).getByRole('button', { name: 'Delete cookies' }))
    fireEvent.click((await row('vimeo')).getByRole('button', { name: 'Delete site' }))

    await waitFor(() => {
      expect(sentBodies(fetchMock, 'DELETE /api/sites/youtube/cookies')).toHaveLength(1)
      expect(sentBodies(fetchMock, 'DELETE /api/sites/vimeo')).toHaveLength(1)
    })
  })

  it('shows the export help', async () => {
    mockApi({ ...base, 'GET /api/sites': () => json(SITES) })
    renderApp('/cookies')

    const help = await row('How to export cookies')
    expect(help.getByText(/private\/incognito window/)).toBeInTheDocument()
    expect(help.getByText(/throwaway account/)).toBeInTheDocument()
    expect(help.getByText('--cookies-from-browser')).toBeInTheDocument()
  })
})
