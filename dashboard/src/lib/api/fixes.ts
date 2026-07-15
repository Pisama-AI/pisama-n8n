import { IS_SAAS } from '@/lib/saas'
import { fetchApi, postApi } from './client'

export interface PatchOp {
  op: string
  target?: string
  node?: string | null
  key?: string
  value?: unknown
}

export interface FixSuggestion {
  explanation: string
  patch_ops: PatchOp[]
  mutated_workflow: Record<string, unknown>
  workflow_id: string | null
}

export interface ApplyResult {
  snapshot: Record<string, unknown>
  applied: Record<string, unknown>
}

export interface PaidStatus {
  enabled: boolean
  plan?: string
  fixQuota?: number
  fixesUsed?: number
}

// Endpoint families differ between the OSS self-host server and the SaaS API.
const FIX = IS_SAAS ? '/api/v1/fixes' : '/api/v1/n8n/fix'
const APPLY = IS_SAAS ? '/api/v1/fixes/apply' : '/api/v1/n8n/apply'
const ROLLBACK = IS_SAAS ? '/api/v1/fixes/rollback' : '/api/v1/n8n/rollback'

export async function getPaidStatus(): Promise<PaidStatus> {
  const raw = await fetchApi<Record<string, unknown>>('/api/v1/paid/status')
  // OSS returns {enabled}; SaaS returns {plan, fix_quota, fixes_used, fixes_enabled}.
  if (IS_SAAS) {
    return {
      enabled: Boolean(raw.fixes_enabled),
      plan: raw.plan as string,
      fixQuota: raw.fix_quota as number,
      fixesUsed: raw.fixes_used as number,
    }
  }
  return { enabled: Boolean(raw.enabled) }
}

export function requestFix(detectionId: string): Promise<FixSuggestion> {
  return postApi(FIX, { detection_id: Number(detectionId) })
}

export function applyFix(
  workflowId: string,
  mutatedWorkflow: Record<string, unknown>,
): Promise<ApplyResult> {
  return postApi(APPLY, { workflow_id: workflowId, mutated_workflow: mutatedWorkflow })
}

export function rollbackFix(
  workflowId: string,
  snapshot: Record<string, unknown>,
): Promise<unknown> {
  return postApi(ROLLBACK, { workflow_id: workflowId, snapshot })
}

// SaaS only: start a Stripe Checkout for the Pro upgrade; returns a redirect URL.
export async function startCheckout(): Promise<string> {
  const origin = typeof window !== 'undefined' ? window.location.origin : ''
  const res = await postApi<{ url: string }>('/api/v1/billing/checkout', {
    success_url: `${origin}/overview?upgraded=1`,
    cancel_url: `${origin}/detections`,
  })
  return res.url
}
