import { IS_SAAS } from '@/lib/saas'
import { postApi } from './client'
import type { ApplyResult } from './fixes'

// Input-schema guardrail repair (fair-code self-host AND multi-tenant SaaS server).
// Deterministic path derivation + destination wiring, distinct from the
// AI-generated FixPanel flow in fixes.ts. Propose + set-destination share one
// path shape across both products; apply/rollback diverge (see below).

export type GuardDestinationKind = 'error_workflow' | 'alert' | 'respond_422'

export interface GuardPathOptions {
  confirmed: string[]
  candidates: string[]
}

export interface GuardConfig {
  kind: 'input_schema'
  paths: string[]
  path_options: GuardPathOptions
  failing_node: string
  destination: GuardDestinationKind | null
  alert_url: string | null
  // Present once a destination has been set.
  fragment_node_names?: string[]
  destination_node_name?: string
  entry_node?: string
  validated_node?: string
  rejected_node?: string
}

export interface GuardRepair {
  id: number
  status: string
  guard_config: GuardConfig
}

export interface GuardDestinationOption {
  kind: GuardDestinationKind
  label: string
  available: boolean
  reason: string | null
}

export interface ProposeGuardrailResponse {
  repair: GuardRepair
  path_options: GuardPathOptions
  destinations: GuardDestinationOption[]
}

export interface N8nWorkflowNode {
  name: string
  type: string
  [key: string]: unknown
}

export interface ProposedWorkflow {
  nodes: N8nWorkflowNode[]
  connections: Record<string, unknown>
}

export interface SetGuardrailDestinationResponse {
  repair: GuardRepair & { proposed_workflow: ProposedWorkflow }
}

export function proposeGuardrail(
  detectionId: number,
  paths?: string[],
): Promise<ProposeGuardrailResponse> {
  return postApi('/api/v1/n8n/guardrail', { detection_id: detectionId, paths })
}

export function setGuardrailDestination(
  repairId: number,
  destination: GuardDestinationKind,
  alertUrl?: string,
): Promise<SetGuardrailDestinationResponse> {
  return postApi(`/api/v1/n8n/repairs/${repairId}/destination`, {
    destination,
    alert_url: alertUrl,
  })
}

// Apply/rollback diverge by product. The fair-code self-host server shares one
// repair-apply endpoint with the AI-fix flow (POST /n8n/apply {repair_id}); the
// multi-tenant SaaS server exposes the guardrail lifecycle under REST-nested
// per-repair paths (POST /n8n/repairs/{id}/apply, no body). Same {repair}
// response either way. In SaaS, apply/rollback are Pro-gated (they write to the
// tenant's live n8n) and return 402 for a free tenant.
export function applyGuardrail(repairId: number): Promise<ApplyResult> {
  return IS_SAAS
    ? postApi(`/api/v1/n8n/repairs/${repairId}/apply`, {})
    : postApi('/api/v1/n8n/apply', { repair_id: repairId })
}

export function rollbackGuardrail(repairId: number): Promise<unknown> {
  return IS_SAAS
    ? postApi(`/api/v1/n8n/repairs/${repairId}/rollback`, {})
    : postApi('/api/v1/n8n/rollback', { repair_id: repairId })
}
