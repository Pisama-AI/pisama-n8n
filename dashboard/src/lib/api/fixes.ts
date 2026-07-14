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
}

export function getPaidStatus(): Promise<{ enabled: boolean }> {
  return fetchApi('/api/v1/paid/status')
}

export function requestFix(detectionId: string): Promise<FixSuggestion> {
  return postApi('/api/v1/n8n/fix', { detection_id: Number(detectionId) })
}
