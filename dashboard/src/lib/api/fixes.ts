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
  // self-host returns a durable local repair id. The hosted API may use its own repair
  // lifecycle while the two products converge, so this remains optional here.
  repair_id?: number
  repair_status?: 'proposed'
}

export interface ApplyResult {
  repair: RepairRecord
}

export interface RepairRecord {
  id: number
  status: string
  workflow_id: string
  applied_at: string | null
  rolled_back_at: string | null
  failure_reason: string | null
}

export interface PaidStatus {
  enabled: boolean
  plan?: string
  fixQuota?: number
  fixesUsed?: number
}

// Endpoint families differ between the fair-code self-host server and the SaaS API.
const FIX = IS_SAAS ? '/api/v1/fixes' : '/api/v1/n8n/fix'

export async function getPaidStatus(): Promise<PaidStatus> {
  const raw = await fetchApi<Record<string, unknown>>('/api/v1/paid/status')
  // self-host returns {enabled}; SaaS returns {plan, fix_quota, fixes_used, fixes_enabled}.
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

// Apply/rollback diverge by product, mirroring guardrail.ts: the fair-code server shares one
// repair-apply endpoint (POST /n8n/apply {repair_id}); the SaaS server runs BOTH repair
// kinds (guardrails and model fixes) through REST-nested per-repair paths
// (POST /n8n/repairs/{id}/apply, no body). Same {repair} response either way. The fix
// suggestion carries repair_id in both products since the SaaS persistent-repair port.
export function applyFix(
  repairId: number,
): Promise<ApplyResult> {
  return IS_SAAS
    ? postApi(`/api/v1/n8n/repairs/${repairId}/apply`, {})
    : postApi('/api/v1/n8n/apply', { repair_id: repairId })
}

export function rollbackFix(
  repairId: number,
): Promise<unknown> {
  return IS_SAAS
    ? postApi(`/api/v1/n8n/repairs/${repairId}/rollback`, {})
    : postApi('/api/v1/n8n/rollback', { repair_id: repairId })
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
