import { test, expect, Page } from '@playwright/test'
import { SELF_HOST_API_BASE } from '../playwright.self-host.config'

// Server rows in the exact shape GET /api/v1/detections returns (ServerDetection).
// Three fired detections across three executions plus one non-fired row, so the
// list's fired-only filter and the overview counts have something real to chew on.
const NOW = Date.now()
const iso = (hoursAgo: number) => new Date(NOW - hoursAgo * 3_600_000).toISOString()

const ROWS = [
  {
    id: 1,
    execution_id: 11,
    detector: 'timeout',
    detected: true,
    confidence: 0.9,
    failure_mode: 'node_timeout',
    explanation: 'Webhook call took 64.0s',
    received_at: iso(2),
    workflow_id: 'wf-a',
    workflow_name: 'Order sync',
    n8n_execution_id: '901',
  },
  {
    id: 2,
    execution_id: 12,
    detector: 'error',
    detected: true,
    confidence: 0.95,
    failure_mode: 'node_error',
    explanation: 'Error rate 50%',
    received_at: iso(5),
    workflow_id: 'wf-a',
    workflow_name: 'Order sync',
    n8n_execution_id: '902',
  },
  {
    id: 3,
    execution_id: 13,
    detector: 'resource',
    detected: true,
    confidence: 0.7,
    failure_mode: 'resource_growth',
    explanation: 'Output grew 40x across the run',
    received_at: iso(26),
    workflow_id: 'wf-b',
    workflow_name: 'Lead enrichment',
    n8n_execution_id: '903',
  },
  {
    id: 4,
    execution_id: 14,
    detector: 'timeout',
    detected: false,
    confidence: 0.1,
    failure_mode: null,
    explanation: '',
    received_at: iso(1),
    workflow_id: 'wf-b',
    workflow_name: 'Lead enrichment',
    n8n_execution_id: '904',
  },
]

const TRACE = {
  available: true,
  kind: 'runtime',
  status: 'success',
  finished: true,
  duration_ms: 64_500,
  error: null,
  last_node: 'Slow Webhook',
  node_count: 2,
  nodes: [
    {
      name: 'Manual Trigger',
      type: 'n8n-nodes-base.manualTrigger',
      ran: true,
      status: 'success',
      execution_time_ms: 3,
      items_out: 1,
      error: null,
      runs: 1,
    },
    {
      name: 'Slow Webhook',
      type: 'n8n-nodes-base.httpRequest',
      ran: true,
      status: 'success',
      execution_time_ms: 64_000,
      items_out: 1,
      error: null,
      runs: 1,
    },
  ],
}

// Intercept every call the self-host dashboard makes to the self-host server. The SSE
// stream is fulfilled with a long client-retry hint so EventSource does not
// reconnect-spam within a test's lifetime.
async function mockServerApi(page: Page) {
  await page.route(`${SELF_HOST_API_BASE}/api/v1/stream**`, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: 'retry: 60000\n\n',
    }),
  )
  await page.route(`${SELF_HOST_API_BASE}/api/v1/detections`, (route) =>
    route.fulfill({ json: ROWS }),
  )
  await page.route(`${SELF_HOST_API_BASE}/api/v1/detections/1`, (route) =>
    route.fulfill({ json: ROWS[0] }),
  )
  await page.route(`${SELF_HOST_API_BASE}/api/v1/detections/1/trace`, (route) =>
    route.fulfill({ json: TRACE }),
  )
  await page.route(`${SELF_HOST_API_BASE}/api/v1/paid/status`, (route) =>
    route.fulfill({ json: { enabled: false } }),
  )
}

test.beforeEach(async ({ page }) => {
  await mockServerApi(page)
})

test('overview renders stats, failure breakdown, and recent activity from server rows', async ({
  page,
}) => {
  await page.goto('/overview')

  await expect(page.getByText('Executions analyzed', { exact: true })).toBeVisible()
  await expect(page.getByText('Detections fired', { exact: true })).toBeVisible()
  await expect(page.getByText('Failures over time')).toBeVisible()

  // 3 of the 4 rows are fired; the non-fired row must not count. The StatCard
  // renders label and value inside one card element.
  const firedCard = page.getByText('Detections fired', { exact: true }).locator('..')
  await expect(firedCard).toContainText('3')

  await expect(page.getByText('Most common failures')).toBeVisible()
  // Recent activity shows the plain-English label of the latest fired rows.
  await expect(page.getByText('Recent activity')).toBeVisible()
  await expect(page.getByText('Node took too long').first()).toBeVisible()
  await expect(page.getByText('A node errored out').first()).toBeVisible()
})

test('detections list shows fired rows only and the type filter narrows them', async ({
  page,
}) => {
  await page.goto('/detections')

  // Fired rows render (asserted on their explanation text, which is unique to a
  // row — the plain-English labels also appear as hidden <option>s in the type
  // filter, so they are not safe row markers). The non-fired row is absent.
  await expect(page.getByText('Webhook call took 64.0s')).toBeVisible()
  await expect(page.getByText('Error rate 50%')).toBeVisible()
  await expect(page.getByText('Output grew 40x across the run')).toBeVisible()

  // Filter to timeout: the error/resource rows disappear.
  await page.locator('select').first().selectOption('timeout')
  await expect(page.getByText('Webhook call took 64.0s')).toBeVisible()
  await expect(page.getByText('Error rate 50%')).toHaveCount(0)
  await expect(page.getByText('Output grew 40x across the run')).toHaveCount(0)
})

test('detection detail deep link renders the narrative and the execution trace', async ({
  page,
}) => {
  // A cold deep link: resolves via GET /detections/1 without the list loaded.
  await page.goto('/detections/1')

  await expect(page.getByText('What happened')).toBeVisible()
  await expect(page.getByText('Webhook call took 64.0s').first()).toBeVisible()
  await expect(page.getByText('Order sync').first()).toBeVisible()

  // The in-app trace panel renders per-node rows from GET /detections/1/trace.
  await expect(page.getByText('Slow Webhook').first()).toBeVisible()
  await expect(page.getByText('Manual Trigger').first()).toBeVisible()
})
