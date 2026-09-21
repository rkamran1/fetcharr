import { fireEvent, screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { json, mockApi, noContent, renderApp, sentBodies } from '@/test/mockApi'

const health = () => json({ status: 'ok', version: '1.2.3' })
const unauthorized = () => json({ detail: 'Not authenticated' }, 401)

function type(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } })
}

describe('auth guard and app shell', () => {
  it('redirects to login when unauthenticated', async () => {
    mockApi({
      'GET /api/auth/me': unauthorized,
      'GET /api/auth/state': () => json({ setup_required: false }),
    })

    renderApp('/settings')

    expect(await screen.findByRole('heading', { name: 'Log in' })).toBeInTheDocument()
  })

  it('redirects to setup when setup is required', async () => {
    mockApi({
      'GET /api/auth/me': unauthorized,
      'GET /api/auth/state': () => json({ setup_required: true }),
    })

    renderApp('/')

    expect(await screen.findByRole('heading', { name: 'Create your account' })).toBeInTheDocument()
  })

  it('setup creates the account and shows the app shell', async () => {
    let signedIn = false // like the server: setup sets the session cookie
    const fetchMock = mockApi({
      'GET /api/auth/me': () => (signedIn ? json({ username: 'owner' }) : unauthorized()),
      'GET /api/auth/state': () => json({ setup_required: !signedIn }),
      'POST /api/auth/setup': () => {
        signedIn = true
        return json({ username: 'owner' }, 201)
      },
      'GET /healthz': health,
    })
    renderApp('/')
    await screen.findByRole('heading', { name: 'Create your account' })

    type('Username', 'owner')
    type('Password', 'correct horse')
    type('Repeat password', 'correct horse')
    fireEvent.click(screen.getByRole('button', { name: 'Create account' }))

    expect(await screen.findByRole('button', { name: 'Log out' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Home' })).toBeInTheDocument()
    expect(sentBodies(fetchMock, 'POST /api/auth/setup')).toEqual([
      { username: 'owner', password: 'correct horse' },
    ])
  })

  it('setup refuses mismatched passwords without calling the API', async () => {
    const fetchMock = mockApi({
      'GET /api/auth/me': unauthorized,
      'GET /api/auth/state': () => json({ setup_required: true }),
    })
    renderApp('/setup')
    await screen.findByRole('heading', { name: 'Create your account' })

    type('Username', 'owner')
    type('Password', 'correct horse')
    type('Repeat password', 'correct horsf')
    fireEvent.click(screen.getByRole('button', { name: 'Create account' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Passwords do not match.')
    expect(sentBodies(fetchMock, 'POST /api/auth/setup')).toEqual([])
  })

  it('login shows the app shell with navigation and version', async () => {
    let signedIn = false
    const fetchMock = mockApi({
      'GET /api/auth/me': () => (signedIn ? json({ username: 'owner' }) : unauthorized()),
      'GET /api/auth/state': () => json({ setup_required: false }),
      'POST /api/auth/login': () => {
        signedIn = true
        return json({ username: 'owner' })
      },
      'GET /healthz': health,
    })
    renderApp('/')
    await screen.findByRole('heading', { name: 'Log in' })

    type('Username', 'owner')
    type('Password', 'correct horse')
    fireEvent.click(screen.getByRole('button', { name: 'Log in' }))

    const nav = await screen.findByRole('navigation', { name: 'Main' })
    expect(nav).toHaveTextContent('Home')
    expect(nav).toHaveTextContent('Settings')
    expect(await screen.findByText('fetcharr 1.2.3')).toBeInTheDocument()
    expect(sentBodies(fetchMock, 'POST /api/auth/login')).toEqual([
      { username: 'owner', password: 'correct horse' },
    ])
  })

  it('login shows an error for wrong credentials', async () => {
    mockApi({
      'GET /api/auth/me': unauthorized,
      'GET /api/auth/state': () => json({ setup_required: false }),
      'POST /api/auth/login': () => json({ detail: 'Invalid username or password' }, 401),
    })
    renderApp('/login')
    await screen.findByRole('heading', { name: 'Log in' })

    type('Username', 'owner')
    type('Password', 'wrong')
    fireEvent.click(screen.getByRole('button', { name: 'Log in' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid username or password')
    expect(screen.getByRole('heading', { name: 'Log in' })).toBeInTheDocument()
  })

  it('logout returns to login', async () => {
    let signedIn = true
    const fetchMock = mockApi({
      'GET /api/auth/me': () => (signedIn ? json({ username: 'owner' }) : unauthorized()),
      'GET /api/auth/state': () => json({ setup_required: false }),
      'POST /api/auth/logout': () => {
        signedIn = false
        return noContent()
      },
      'GET /healthz': health,
    })
    renderApp('/')

    fireEvent.click(await screen.findByRole('button', { name: 'Log out' }))

    expect(await screen.findByRole('heading', { name: 'Log in' })).toBeInTheDocument()
    expect(sentBodies(fetchMock, 'POST /api/auth/logout')).toHaveLength(1)
  })

  it('a 401 from any request returns to login', async () => {
    let signedIn = true
    mockApi({
      'GET /api/auth/me': () => (signedIn ? json({ username: 'owner' }) : unauthorized()),
      'GET /api/auth/state': () => json({ setup_required: false }),
      'POST /api/auth/api-key': () => {
        signedIn = false // the session expired on the server
        return unauthorized()
      },
      'GET /healthz': health,
    })
    renderApp('/settings')

    fireEvent.click(await screen.findByRole('button', { name: 'Regenerate API key' }))

    expect(await screen.findByRole('heading', { name: 'Log in' })).toBeInTheDocument()
  })
})

describe('app shell', () => {
  it('the shell links to Cookies', async () => {
    mockApi({
      'GET /api/auth/me': () => json({ username: 'owner' }),
      'GET /healthz': health,
      'GET /api/sites': () => json([]),
    })
    renderApp('/')

    fireEvent.click(await screen.findByRole('link', { name: 'Cookies' }))

    expect(await screen.findByRole('heading', { name: 'Cookies' })).toBeInTheDocument()
  })

  it('navigates between the pages that exist', async () => {
    mockApi({ 'GET /api/auth/me': () => json({ username: 'owner' }), 'GET /healthz': health })
    renderApp('/')

    fireEvent.click(await screen.findByRole('link', { name: 'Settings' }))

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Settings' })).toBeInTheDocument(),
    )
  })

  it('opens the TV wizard from the home page', async () => {
    mockApi({
      'GET /api/auth/me': () => json({ username: 'owner' }),
      'GET /healthz': health,
      'GET /api/arr/sonarr/series?q=&missing=true': () => json({ series: [] }),
    })
    renderApp('/')

    fireEvent.click(await screen.findByRole('link', { name: /TV Show/ }))

    expect(
      await screen.findByRole('heading', { name: 'Download TV Show' }),
    ).toBeInTheDocument()
    // The landing page is the missing list itself, with nothing to paste first (AC17).
    expect(
      await screen.findByText("Sonarr isn't missing episodes from anything that matches."),
    ).toBeInTheDocument()
  })
})
