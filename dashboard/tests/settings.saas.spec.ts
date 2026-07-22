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

test('ingest keys: shows the node API URL and mints a key exactly once', async ({ page }) => {
  await page.route('**/api/backend/api/v1/connections', (r) => r.fulfill({ json: [CONNECTION] }))
  await page.route('**/api/backend/api/v1/api-keys', (r) => {
    if (r.request().method() === 'POST') {
      return r.fulfill({
        json: { api_key: 'pn8n_testplaintext', note: 'Store this now — it is not shown again.' },
      })
    }
    return r.fulfill({
      json: [{ id: 'k1', name: 'ingest', prefix: 'pn8n_abcdefg', created_at: '2026-07-20T10:00:00Z' }],
    })
  })

  await page.goto('/settings')
  // The community-node credential needs the PUBLIC API origin; the card must state it.
  await expect(page.getByText('/api/v1', { exact: false }).first()).toBeVisible()
  // Existing keys list by prefix only.
  await expect(page.getByText('pn8n_abcdefg')).toBeVisible()

  // Minting shows the plaintext once, with the copy-now warning.
  const [req] = await Promise.all([
    page.waitForRequest(
      (r) => r.url().includes('/api/v1/api-keys') && r.method() === 'POST',
    ),
    page.getByRole('button', { name: 'Create ingest key' }).click(),
  ])
  expect(req.method()).toBe('POST')
  await expect(page.getByText('pn8n_testplaintext')).toBeVisible()
  await expect(page.getByText('Copy this key now')).toBeVisible()
})

test('MCP keys: mints with scope=mcp and badges the scope in the list', async ({ page }) => {
  await page.route('**/api/backend/api/v1/connections', (r) => r.fulfill({ json: [CONNECTION] }))
  await page.route('**/api/backend/api/v1/api-keys', (r) => {
    if (r.request().method() === 'POST') {
      return r.fulfill({ json: { api_key: 'pn8nm_testplaintext', scope: 'mcp' } })
    }
    return r.fulfill({
      json: [
        {
          id: 'k2',
          name: 'mcp',
          prefix: 'pn8nm_abcdef',
          scope: 'mcp',
          created_at: '2026-07-22T10:00:00Z',
        },
      ],
    })
  })

  await page.goto('/settings')
  // Scope badge on the listed key + the boundary explained in the card copy.
  await expect(page.getByText('pn8nm_abcdef')).toBeVisible()
  // The badge text is 'mcp' in the DOM; CSS renders it uppercase.
  await expect(page.getByText('mcp', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('cannot ingest', { exact: false })).toBeVisible()

  const [req] = await Promise.all([
    page.waitForRequest(
      (r) => r.url().includes('/api/v1/api-keys') && r.method() === 'POST',
    ),
    page.getByRole('button', { name: 'Create MCP key' }).click(),
  ])
  expect(req.postDataJSON()).toEqual({ scope: 'mcp' })
  await expect(page.getByText('pn8nm_testplaintext')).toBeVisible()
})
