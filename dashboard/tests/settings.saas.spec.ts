import { test, expect } from '@playwright/test'
import { sessionCookie } from './_auth'

// SaaS settings smoke. The route is auth-guarded and reads /me + /connections +
// /billing/portal through the BFF; we forge the session and mock the BFF so the
// SaaS settings UI + billing wiring are exercised without Google auth or the
// cloud backend. Shapes mirror saas_server/app.py.

const ME = {
  tenant_id: 't1',
  name: 'founder@pisama.ai',
  plan: 'pro',
  connections: 1,
  onboarded: true,
}

const CONNECTION = {
  id: 'c1',
  base_url: 'https://acme.app.n8n.cloud',
  active: true,
  poll_interval_seconds: 300,
  last_polled_at: '2026-07-15T10:00:00.000Z',
  last_error: null,
}

test.beforeEach(async ({ context, page }) => {
  await context.addCookies([await sessionCookie()])
  await page.route('**/api/backend/api/v1/me', (r) => r.fulfill({ json: ME }))
  await page.route('**/api/backend/api/v1/billing/portal', (r) =>
    r.fulfill({ json: { url: '/settings?portal=done' } }),
  )
})

test('renders account + connection and wires the billing portal', async ({ page }) => {
  await page.route('**/api/backend/api/v1/connections', (r) => r.fulfill({ json: [CONNECTION] }))

  await page.goto('/settings')
  await expect(page.getByRole('heading', { name: 'Settings' }).first()).toBeVisible()

  // Account card (email also shows in the header pill → first match is enough).
  await expect(page.getByText('founder@pisama.ai').first()).toBeVisible()
  await expect(page.getByText('PRO', { exact: false }).first()).toBeVisible()

  // Connection row from GET /connections.
  await expect(page.getByText('https://acme.app.n8n.cloud')).toBeVisible()

  // Billing wiring: clicking "Manage subscription" issues the portal POST.
  const [req] = await Promise.all([
    page.waitForRequest('**/api/backend/api/v1/billing/portal'),
    page.getByRole('button', { name: 'Manage subscription' }).click(),
  ])
  expect(req.method()).toBe('POST')
})

test('shows the connect CTA when there are no connections', async ({ page }) => {
  await page.route('**/api/backend/api/v1/connections', (r) => r.fulfill({ json: [] }))

  await page.goto('/settings')
  await expect(page.getByRole('button', { name: 'Connect n8n' })).toBeVisible()
})
