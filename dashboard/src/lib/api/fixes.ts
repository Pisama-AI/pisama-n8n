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

export function getPaidStatus(): Promise<{ enabled: boolean }> {
  return fetchApi('/api/v1/paid/status')
}

export function requestFix(detectionId: string): Promise<FixSuggestion> {
  return postApi('/api/v1/n8n/fix', { detection_id: Number(detectionId) })
}

export function applyFix(
  workflowId: string,
  mutatedWorkflow: Record<string, unknown>,
): Promise<ApplyResult> {
  return postApi('/api/v1/n8n/apply', {
    workflow_id: workflowId,
    mutated_workflow: mutatedWorkflow,
  })
}

export function rollbackFix(
  workflowId: string,
  snapshot: Record<string, unknown>,
): Promise<unknown> {
  return postApi('/api/v1/n8n/rollback', { workflow_id: workflowId, snapshot })
}
