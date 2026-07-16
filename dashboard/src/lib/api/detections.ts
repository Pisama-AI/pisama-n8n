import { fetchApi, postApi } from './client'

// Raw row shape returned by the server's GET /api/v1/detections.
export interface ServerDetection {
  id: number
  execution_id: number
  detector: string
  detected: boolean
  confidence: number
  failure_mode: string | null
  explanation: string
  // Added by the server (join on executions.received_at); may be absent on
  // older rows, so the adapter falls back.
  received_at?: string
  // Workflow context (join on executions). workflow_name/n8n_execution_id are
  // null on legacy rows ingested before those columns existed.
  workflow_id?: string | null
  workflow_name?: string | null
  n8n_execution_id?: string | null
  feedback?: DetectionFeedback | null
  reliability_case?: ReliabilityCase | null
}

// Shape the copied DetectionListItem (and the detail view) expect. `detected`
// and `failure_mode` are additive (DetectionListItem ignores them) so the
// overview/detail views can filter fired detections and show the raw fields.
export interface Detection {
  id: string
  detection_type: string
  trace_id: string
  confidence: number
  method: string
  business_impact?: string
  validated: boolean
  false_positive?: boolean
  created_at: string
  detected: boolean
  failure_mode: string | null
  workflow_id?: string | null
  workflow_name?: string | null
  n8n_execution_id?: string | null
  details?: {
    severity?: string
    affected_agents?: number
  }
  feedback?: DetectionFeedback | null
  reliability_case?: ReliabilityCase | null
}

export type FeedbackVerdict = 'useful' | 'not_useful' | 'fixed_manually'

export interface DetectionFeedback {
  id: number
  detection_id: number
  verdict: FeedbackVerdict
  note: string | null
  created_at: string
}

export interface ReliabilityCase {
  id: number
  repair_id: number
  detection_id: number
  workflow_id: string
  detector: string
  failure_mode: string | null
  status: 'observing' | 'recurred' | 'prevented' | 'inconclusive' | 'rolled_back'
  successful_execution_count: number
  recurrence_count: number
  first_success_execution_id: number | null
  first_recurrence_execution_id: number | null
  required_successful_executions: number
  ready_for_outcome_review: boolean
  outcome_note: string | null
  created_at: string
  updated_at: string
  outcome_at: string | null
}

function severityFromConfidence(confidence: number): string {
  if (confidence >= 0.8) return 'high'
  if (confidence >= 0.5) return 'medium'
  return 'low'
}

export function adaptDetection(row: ServerDetection): Detection {
  return {
    id: String(row.id),
    detection_type: row.detector,
    trace_id: String(row.execution_id),
    confidence: row.confidence,
    method: 'n8n',
    business_impact: row.explanation,
    validated: false,
    created_at: row.received_at ?? new Date().toISOString(),
    detected: row.detected,
    failure_mode: row.failure_mode,
    workflow_id: row.workflow_id ?? null,
    workflow_name: row.workflow_name ?? null,
    n8n_execution_id: row.n8n_execution_id ?? null,
    feedback: row.feedback ?? null,
    reliability_case: row.reliability_case ?? null,
    details: {
      severity: severityFromConfidence(row.confidence),
    },
  }
}

export async function getDetections(): Promise<Detection[]> {
  const rows = await fetchApi<ServerDetection[]>('/api/v1/detections')
  return rows.map(adaptDetection)
}

// Fetch a single detection by id (GET /api/v1/detections/{id}), so the detail
// view works on a cold deep link without loading the whole list.
export async function getDetection(id: string): Promise<Detection> {
  const row = await fetchApi<ServerDetection>(`/api/v1/detections/${id}`)
  return adaptDetection(row)
}

export function submitDetectionFeedback(
  detectionId: string,
  verdict: FeedbackVerdict,
): Promise<DetectionFeedback> {
  return postApi(`/api/v1/detections/${detectionId}/feedback`, { verdict })
}

// Per-node execution trace behind a detection (GET /detections/{id}/trace).
export interface TraceNode {
  name: string
  type: string | null
  ran: boolean
  status: 'success' | 'error' | 'unknown'
  execution_time_ms: number | null
  items_out: number | null
  error: string | null
  runs: number
}

export interface Trace {
  available: boolean
  kind?: 'runtime' | 'static'
  status?: 'success' | 'error' | null
  finished?: boolean | null
  duration_ms?: number | null
  error?: string | null
  last_node?: string | null
  node_count?: number
  nodes?: TraceNode[]
}

export function getDetectionTrace(id: string): Promise<Trace> {
  return fetchApi<Trace>(`/api/v1/detections/${id}/trace`)
}
