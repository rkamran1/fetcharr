import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// Object form on purpose: Vite's string shorthand sets changeOrigin: true, which rewrites
// Host and makes the backend's CSRF check (Origin must match Host) reject every write.
const proxy = {
  target: process.env.VITE_PROXY_TARGET ?? 'http://localhost:8000',
  changeOrigin: false,
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': path.resolve(import.meta.dirname, './src') },
  },
  server: {
    proxy: {
      '/healthz': proxy,
      '/api': proxy,
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
  },
})
