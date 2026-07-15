import { defineConfig, devices } from '@playwright/test'
import { NEXTAUTH_KEY } from './tests/_auth'

const PORT = 3555
const BASE = `http://localhost:${PORT}`

// Smoke config: boots the dashboard in SaaS mode (billing on) and runs specs that
// forge a session + mock the BFF, so no Google auth or cloud backend is required.
export default defineConfig({
  testDir: './tests',
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
      // The BFF forwards here, but every /api/backend call is browser-mocked, so
      // this is never actually reached.
      SAAS_API_URL: 'http://127.0.0.1:59999',
    },
  },
})
