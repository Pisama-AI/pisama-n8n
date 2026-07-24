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
  await expect(response.json()).resolves.toMatchObject({ build_revision: 'unknown' })
})
