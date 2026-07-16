import { defineConfig, devices } from '@playwright/test'

const PORT = 3556
const BASE = `http://localhost:${PORT}`

// Where the OSS dashboard believes the self-host server lives. Nothing listens
// here — every call is intercepted in-browser by page.route() — but pinning it
// keeps the specs hermetic even if a real server is running on :8400.
export const OSS_API_BASE = 'http://127.0.0.1:8455'

// OSS-mode smoke: boots the dashboard exactly as a self-hoster runs it
// (NEXT_PUBLIC_SAAS unset/0, direct API calls) and mocks the server API at the
// browser boundary. Runs as a SEPARATE playwright invocation from the SaaS
// config because Next 16 allows only one `next dev` per project directory —
// see package.json's test:e2e, which chains the two configs sequentially.
export default defineConfig({
  testDir: './tests',
  testMatch: /oss\..*\.spec\.ts/,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: 'list',
  use: { baseURL: BASE, trace: 'off' },
  projects: [{ name: 'chromium-oss', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: `npx next dev -p ${PORT}`,
    url: BASE,
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      NEXT_PUBLIC_SAAS: '0',
      NEXT_PUBLIC_API_BASE: OSS_API_BASE,
    },
  },
})
