/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The browser calls the data plane directly (VITE_API_BASE_URL), as it will in
// production; the API's CORS setting allows the dev server origin.
export default defineConfig({
  plugins: [react()],
  server: {
    // Must match FRONTEND_ORIGIN in .env.test (CORS). strictPort: fail instead of silently
    // moving to another port that the API would reject. Pilot: npm run dev -- --port 5174
    port: 5175,
    strictPort: true,
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
  },
})
