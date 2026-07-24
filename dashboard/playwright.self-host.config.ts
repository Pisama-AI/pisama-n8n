import { defineConfig, devices } from '@playwright/test'

const PORT = 3556
const BASE = `http://localhost:${PORT}`
const SERVER_PORT = 8455
const E2E_DB = `/tmp/pisama-n8n-dashboard-e2e-${process.pid}.db`
const PYTHON = process.env.PISAMA_E2E_PYTHON || 'python'

export const SELF_HOST_API_BASE = `http://127.0.0.1:${SERVER_PORT}`
export const SELF_HOST_API_KEY = 'pisama-e2e-real-server-key'

// Self-host verification boots the real FastAPI server, a fresh real SQLite
// database, and the dashboard. The spec ingests a sanitized n8n Cloud capture
// through the authenticated HTTP endpoint before exercising the browser flow.
export default defineConfig({
  testDir: './tests',
  testMatch: /self-host\..*\.spec\.ts/,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: 'list',
  use: { baseURL: BASE, trace: 'off' },
  projects: [{ name: 'chromium-self-host', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: `${PYTHON} -m uvicorn pisama_n8n_server.app:app --host 127.0.0.1 --port ${SERVER_PORT}`,
      url: `${SELF_HOST_API_BASE}/healthz`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        DATABASE_URL: `sqlite:///${E2E_DB}`,
        PISAMA_API_KEY: SELF_HOST_API_KEY,
        PISAMA_CORS_ORIGINS: BASE,
        PISAMA_BUILD_REVISION: 'dashboard-e2e',
      },
    },
    {
      command: `npx next dev -p ${PORT}`,
      url: BASE,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        NEXT_PUBLIC_SAAS: '0',
        NEXT_PUBLIC_API_BASE: SELF_HOST_API_BASE,
        NEXT_PUBLIC_API_KEY: SELF_HOST_API_KEY,
      },
    },
  ],
})
