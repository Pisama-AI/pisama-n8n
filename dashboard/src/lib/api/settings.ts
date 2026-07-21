import { deleteApi, fetchApi, postApi } from './client'

// Shapes mirror the SaaS backend (saas_server/app.py). OSS mode only uses syncOss.
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

// SaaS: poll one tenant connection now. OSS: the env-configured single connection.
export function syncConnection(id: string): Promise<SyncSummary> {
  return postApi(`/api/v1/connections/${id}/sync`, {})
}

export function syncOss(): Promise<SyncSummary> {
  return postApi('/api/v1/n8n/sync', {})
}

// SaaS ingest keys (pn8n_...): authenticate pushed executions — the n8n-nodes-pisama
// community node or direct POSTs to /api/v1/n8n/webhook. Plaintext is returned ONCE
// at mint time; afterwards only the prefix is listable.
export interface IngestKey {
  id: string
  name?: string | null
  prefix: string
  created_at: string
}

export function listIngestKeys(): Promise<IngestKey[]> {
  return fetchApi('/api/v1/api-keys')
}

export function createIngestKey(): Promise<{ api_key: string }> {
  return postApi('/api/v1/api-keys', {})
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
