import { fetchApi } from './client'

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
  details?: {
    severity?: string
    affected_agents?: number
  }
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
    details: {
      severity: severityFromConfidence(row.confidence),
    },
  }
}

export async function getDetections(): Promise<Detection[]> {
  const rows = await fetchApi<ServerDetection[]>('/api/v1/detections')
  return rows.map(adaptDetection)
}
