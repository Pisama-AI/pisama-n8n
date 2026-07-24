import { defineConfig, devices } from '@playwright/test'
const PORT = 3555
const BASE = `http://localhost:${PORT}`
const NEXTAUTH_KEY = 'pisama-n8n-e2e-key-at-least-32-characters-xx'

// Public SaaS verification. Authenticated settings require a real Google account
// and live cloud backend, so this local suite checks only the real unauthenticated
// journey and never forges a session or substitutes an API.
export default defineConfig({
  testDir: './tests',
  testMatch: /saas\.public\.spec\.ts/,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: 'list',
  use: { baseURL: BASE, trace: 'off' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: `npx next dev -p ${PORT}`,
    url: BASE,
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      NEXT_PUBLIC_SAAS: '1',
      NEXT_PUBLIC_BILLING: '1',
      NEXTAUTH_URL: BASE,
      NEXTAUTH_SECRET: NEXTAUTH_KEY,
    },
  },
})
