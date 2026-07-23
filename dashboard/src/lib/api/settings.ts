import { deleteApi, fetchApi, postApi } from './client'

// Shapes mirror the SaaS backend (saas_server/app.py). Self-hosted mode only uses syncSelfHosted.
export interface Me {
  tenant_id: string
  name?: string // sign-in email for SaaS tenants
  plan?: string
  connections?: number
  onboarded?: boolean
}

export interface Connection {
  id: string
  base_url: string
  active: boolean
  poll_interval_seconds?: number
  last_polled_at: string | null
  last_error: string | null
}

export interface SyncSummary {
  new?: number
  [k: string]: unknown
}

export function getMe(): Promise<Me> {
  return fetchApi('/api/v1/me')
}

export function listConnections(): Promise<Connection[]> {
  return fetchApi('/api/v1/connections')
}

// SaaS: poll one tenant connection now. self-host: the env-configured single connection.
export function syncConnection(id: string): Promise<SyncSummary> {
  return postApi(`/api/v1/connections/${id}/sync`, {})
}

export function syncSelfHosted(): Promise<SyncSummary> {
  return postApi('/api/v1/n8n/sync', {})
}

// SaaS tenant keys. Scope 'ingest' (pn8n_...) authenticates pushed executions — the
// n8n-nodes-pisama community node or direct POSTs to /api/v1/n8n/webhook. Scope 'mcp'
// (pn8nm_...) is the durable read+propose credential for MCP clients (Claude Code,
// Cursor); it can never ingest, and an ingest key can never read. Plaintext is
// returned ONCE at mint time; afterwards only the prefix is listable.
export type ApiKeyScope = 'ingest' | 'mcp'

export interface IngestKey {
  id: string
  name?: string | null
  prefix: string
  scope?: ApiKeyScope
  created_at: string
}

export function listIngestKeys(): Promise<IngestKey[]> {
  return fetchApi('/api/v1/api-keys')
}

export function createIngestKey(scope: ApiKeyScope = 'ingest'): Promise<{ api_key: string }> {
  return postApi('/api/v1/api-keys', { scope })
}

export function revokeIngestKey(id: string): Promise<void> {
  return deleteApi(`/api/v1/api-keys/${id}`)
}

// SaaS: open the Stripe customer portal (manage/cancel subscription).
export async function openBillingPortal(): Promise<string> {
  const origin = typeof window !== 'undefined' ? window.location.origin : ''
  const res = await postApi<{ url: string }>('/api/v1/billing/portal', {
    return_url: `${origin}/settings`,
  })
  return res.url
}
