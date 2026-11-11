/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'

/** A path relative to this file, absolute. */
const here = (path: string) => fileURLToPath(new URL(path, import.meta.url))

// The browser calls the data plane directly (VITE_API_BASE_URL), as it will in
// production; the API's CORS setting allows the dev server origin. Start it with
// `./dev.ps1 dashboard [-Env pilot]`, which sets the port and the API address.
export default defineConfig({
  plugins: [react()],
  // The tests read the formula sheet's text (App.test.tsx: every figure on a page names a
  // formula in it). Only under Vitest: the app never gets it.
  define: process.env.VITEST
    ? { __FORMULA_SHEET__: JSON.stringify(readFileSync(here('../docs/formula-sheet.md'), 'utf-8')) }
    : {},
  server: {
    // This computer only: there is no login yet (ADR-049).
    host: '127.0.0.1',
    // Must match FRONTEND_ORIGIN in .env.test (CORS). strictPort: fail instead of silently
    // moving to another port that the API would reject. Pilot: 5174, set by dev.ps1.
    port: 5175,
    strictPort: true,
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
    // The stylesheet is read as text by components/loading/Loading.test.tsx (the reduced-motion
    // rule); without this, the tests see every CSS file as empty.
    css: { include: [/index\.css/] },
  },
})
