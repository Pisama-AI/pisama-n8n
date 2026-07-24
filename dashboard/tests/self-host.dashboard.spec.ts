import { expect, test } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'

import { SELF_HOST_API_BASE, SELF_HOST_API_KEY } from '../playwright.self-host.config'

const CAPTURE = resolve(
  __dirname,
  '../../server/tests/fixtures/executions/data_contract/CLOUD-112117-missing-required-value.json',
)

let schemaDetectionId: number

test.beforeAll(async ({ request }) => {
  const execution = JSON.parse(await readFile(CAPTURE, 'utf8'))
  const ingested = await request.post(`${SELF_HOST_API_BASE}/api/v1/n8n/webhook`, {
    headers: { Authorization: `Bearer ${SELF_HOST_API_KEY}` },
    data: execution,
  })
  expect(ingested.ok(), await ingested.text()).toBeTruthy()

  const detections = await request.get(`${SELF_HOST_API_BASE}/api/v1/detections`, {
    headers: { Authorization: `Bearer ${SELF_HOST_API_KEY}` },
  })
  expect(detections.ok(), await detections.text()).toBeTruthy()
  const rows = (await detections.json()) as Array<{
    id: number
    detector: string
    detected: boolean
  }>
  const schema = rows.find((row) => row.detector === 'schema' && row.detected)
  expect(schema).toBeDefined()
  schemaDetectionId = schema!.id
})

test('overview renders persisted findings and operational health from the real server', async ({
  page,
}) => {
  await page.goto('/overview')

  await expect(page.getByText('Executions analyzed', { exact: true })).toBeVisible()
  await expect(page.getByText('Detections fired', { exact: true })).toBeVisible()
  await expect(page.getByText('Failures over time')).toBeVisible()
  await expect(page.getByText('Most common failures')).toBeVisible()
  await expect(page.getByText('Data shape mismatch').first()).toBeVisible()
  await expect(page.getByText('A node errored out').first()).toBeVisible()
  await expect(page.getByText('No failure alert workflow').first()).toBeVisible()
  await expect(page.getByText('Operational health')).toBeVisible()
  await expect(page.getByText('Pisama prevention experiment baseline', { exact: false })).toBeVisible()
})

test('detections list filters the persisted real execution by detector type', async ({ page }) => {
  await page.goto('/detections')

  await expect(page.getByRole('link', { name: /Data shape mismatch/ })).toBeVisible()
  await expect(page.getByRole('link', { name: /A node errored out/ })).toBeVisible()
  await expect(page.getByRole('link', { name: /No failure alert workflow/ })).toBeVisible()

  await page.getByLabel('Filter by type').selectOption('schema')
  await expect(page.getByRole('link', { name: /Data shape mismatch/ })).toBeVisible()
  await expect(page.getByRole('link', { name: /A node errored out/ })).toHaveCount(0)
  await expect(page.getByRole('link', { name: /No failure alert workflow/ })).toHaveCount(0)
})

test('detection deep link renders evidence and the recorded node trace', async ({ page }) => {
  await page.goto(`/detections/${schemaDetectionId}`)

  await expect(page.getByText('What happened')).toBeVisible()
  await expect(page.getByText('Data shape mismatch').first()).toBeVisible()
  await expect(page.getByText('Evidence used')).toBeVisible()
  await expect(page.getByText('Observed missing field', { exact: false }).first()).toBeVisible()
  await expect(page.getByText('Baseline webhook').first()).toBeVisible()
  await expect(page.getByText('Cannot read properties of undefined', { exact: false }).first()).toBeVisible()
})

test('unauthorized API reads are rejected while the configured dashboard remains usable', async ({
  request,
  page,
}) => {
  const unauthorized = await request.get(`${SELF_HOST_API_BASE}/api/v1/detections`)
  expect(unauthorized.status()).toBe(401)

  await page.goto('/detections')
  await expect(page.getByRole('link', { name: /Data shape mismatch/ })).toBeVisible()
})

test('settings shows the real self-host connection and paid-feature state', async ({ page }) => {
  await page.goto('/settings')

  await expect(page.getByRole('heading', { name: 'Settings', level: 2 })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Dashboard API key' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'n8n connection' })).toBeVisible()
  await expect(page.getByText('Not configured. Set')).toBeVisible()
  await expect(page.getByText(SELF_HOST_API_BASE)).toBeVisible()
})

test('self-host onboarding routes to the supported settings flow', async ({ page }) => {
  await page.goto('/onboarding')

  await expect(page).toHaveURL('/settings')
  await expect(page.getByText('Connection and access for this self-hosted instance.')).toBeVisible()
})
