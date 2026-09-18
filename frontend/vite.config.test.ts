// @vitest-environment node
import { createServer as createHttpServer, type IncomingHttpHeaders } from 'node:http'
import type { AddressInfo } from 'node:net'
import path from 'node:path'
import { createServer } from 'vite'
import { expect, it } from 'vitest'

// The backend's CSRF check compares Origin with Host, so the dev proxy must pass the
// browser's Host through unchanged (M1 AC16).
it('dev proxy forwards /api and /healthz with the browser Host header', async () => {
  const seen: IncomingHttpHeaders[] = []
  const backend = createHttpServer((req, res) => {
    seen.push(req.headers)
    res.setHeader('Content-Type', 'application/json')
    res.end('{}')
  })
  await new Promise<void>((resolve) => backend.listen(0, '127.0.0.1', resolve))
  process.env.VITE_PROXY_TARGET = `http://127.0.0.1:${(backend.address() as AddressInfo).port}`
  const vite = await createServer({
    configFile: path.resolve(import.meta.dirname, 'vite.config.ts'),
    server: { host: '127.0.0.1', port: 0 },
    logLevel: 'silent',
  })
  try {
    await vite.listen()
    const origin = `127.0.0.1:${(vite.httpServer!.address() as AddressInfo).port}`
    for (const url of ['/api/auth/state', '/healthz']) {
      expect((await fetch(`http://${origin}${url}`)).status).toBe(200)
    }

    expect(seen.map((headers) => headers.host)).toEqual([origin, origin])
  } finally {
    await vite.close()
    backend.close()
    delete process.env.VITE_PROXY_TARGET
  }
})
