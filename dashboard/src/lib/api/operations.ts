import { fetchApi } from './client'

export interface OperationalEvent {
  id: number
  event_type: string
  details: Record<string, unknown>
  created_at: string
}

export interface OperationsSummary {
  executions_analyzed: number
  detections_fired: number
  last_ingested_at: string | null
  fired_by_detector: Record<string, number>
  repairs_by_status: Record<string, number>
  feedback_by_verdict: Record<string, number>
  latest_events: Record<string, OperationalEvent>
}

export function getOperationsSummary(): Promise<OperationsSummary> {
  return fetchApi<OperationsSummary>('/api/v1/operations/summary')
}
