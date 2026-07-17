import { postApi } from './client'

// Input-schema guardrail repair (OSS n8n server only). Deterministic path
// derivation + destination wiring, distinct from the AI-generated FixPanel
// flow in fixes.ts. Reuse applyFix/rollbackFix from fixes.ts for the shared
// apply/rollback lifecycle instead of duplicating those calls here.

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

// applyFix / rollbackFix already point at /api/v1/n8n/apply and
// /api/v1/n8n/rollback on the OSS server (see fixes.ts) and take the same
// {repair_id} shape the guardrail repair record uses, so GuardPanel imports
// those directly rather than duplicating them here.
export { applyFix, rollbackFix } from './fixes'
