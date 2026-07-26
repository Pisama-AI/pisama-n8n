import { expect, test } from '@playwright/test'


test('public landing exposes deployment choices and package links', async ({ page }) => {
  await page.goto('/')

  await expect(
    page.getByRole('heading', { name: /Your n8n workflows fail quietly.*This catches them/ }),
  ).toBeVisible()
  await expect(page.getByText('Self-hosted', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('Cloud', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('Pro preview', { exact: true }).first()).toBeVisible()
  await expect(page.getByRole('link', { name: 'View on npm' })).toHaveAttribute(
    'href',
    'https://www.npmjs.com/package/n8n-nodes-pisama',
  )
})


test('unauthenticated dashboard routes preserve the destination through sign-in', async ({
  page,
}) => {
  await page.goto('/detections/42')

  await expect(page).toHaveURL(/\/sign-in\?callbackUrl=%2Fdetections%2F42$/)
  await expect(page.getByRole('button', { name: 'Continue with Google' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Self-host it' })).toHaveAttribute(
    'href',
    'https://github.com/Pisama-AI/pisama-n8n',
  )
})

test('hosted onboarding requires a session and preserves its destination', async ({ page }) => {
  await page.goto('/onboarding')

  await expect(page).toHaveURL(/\/sign-in\?callbackUrl=%2Fonboarding$/)
  await expect(page.getByRole('button', { name: 'Continue with Google' })).toBeVisible()
})

test('build provenance route is reachable without a session', async ({ request }) => {
  const response = await request.get('/api/version')

  expect(response.ok()).toBeTruthy()
  expect(response.headers()['cache-control']).toBe('public, max-age=0, must-revalidate')
  await expect(response.json()).resolves.toEqual({
    service: 'pisama-n8n-dashboard',
    version: '0.1.0',
    build_revision: 'f'.repeat(40),
    source_repository: 'https://github.com/Pisama-AI/pisama-n8n',
    source_revision_url: null,
  })
})

test('capability contract is public at the documented route', async ({ request }) => {
  const response = await request.get('/api/v1/capabilities')

  expect(response.ok()).toBeTruthy()
  expect(response.headers()['cache-control']).toBe('public, max-age=0, must-revalidate')
  expect(response.headers()['x-pisama-build-revision']).toBe('f'.repeat(40))
  expect(response.headers()['x-pisama-source-repository']).toBe(
    'https://github.com/Pisama-AI/pisama-n8n',
  )
  expect(response.headers()['x-pisama-source-revision-url']).toBeUndefined()

  const manifest = await response.json()
  expect(manifest.schema_version).toBe(1)
  expect(manifest.canonical_url).toBe('https://pisama.ai/product-capabilities.json')
  expect(manifest.products.map((product: { id: string }) => product.id)).toEqual(
    expect.arrayContaining(['n8n_self_hosted', 'n8n_cloud_free', 'n8n_pro']),
  )
  const n8nPro = manifest.products.find(
    (product: { id: string; capabilities: Record<string, string> }) =>
      product.id === 'n8n_pro',
  )
  expect(n8nPro.capabilities.team_governance).toBe('Not included')
})
