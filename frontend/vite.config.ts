/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The browser calls the data plane directly (VITE_API_BASE_URL), as it will in
// production; the API's CORS setting allows the dev server origin. Start it with
// `./dev.ps1 dashboard [-Env pilot]`, which sets the port and the API address.
export default defineConfig({
  plugins: [react()],
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
  },
})
