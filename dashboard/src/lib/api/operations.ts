import { fetchApi } from './client'

export interface OperationalEvent {
  id: number
  event_type: string
  details: Record<string, unknown>
  created_at: string
}

export interface ReliabilityMetrics {
  diagnosis: {
    accepted: number
    rejected: number
    reviewed: number
    acceptance_rate: number | null
  }
  remediation: {
    prevented: number
    recurred: number
    inconclusive: number
    verified_outcomes: number
    verified_remediation_rate: number | null
    recurrence_reduction: null
    recurrence_reduction_note: string
  }
  time_to_applied_workflow_control: {
    sample_size: number
    median_seconds: number | null
    p90_seconds: number | null
  }
  durable_controls: {
    applied_workflow_controls: number
    share: null
    share_note: string
  }
}

export interface OperationsSummary {
  executions_analyzed: number
  detections_fired: number
  last_ingested_at: string | null
  fired_by_detector: Record<string, number>
  repairs_by_status: Record<string, number>
  feedback_by_verdict: Record<string, number>
  reliability_cases_by_status: Record<string, number>
  reliability_metrics: ReliabilityMetrics
  latest_events: Record<string, OperationalEvent>
}

export function getOperationsSummary(): Promise<OperationsSummary> {
  return fetchApi<OperationsSummary>('/api/v1/operations/summary')
}
