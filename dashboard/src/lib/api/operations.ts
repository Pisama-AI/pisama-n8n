import { fetchApi } from './client'

export interface OperationalEvent {
  id: number
  event_type: string
  details: Record<string, unknown>
  created_at: string
}

// Per-detector diagnosis slice (servers >= 2026-07-20; absent on older ones).
export interface DetectorDiagnosis {
  fired: number
  seen: number
  accepted: number
  rejected: number
  reviewed: number
  acceptance_rate: number | null
}

export interface DurableControlKind {
  proposed: number
  applied: number
  durable: number
  share: number | null
  note?: string
}

// Every field added by the 2026-07-20 canonical shape is OPTIONAL: the shared
// dashboard must render against any server vintage during a deploy window, so new
// cells appear only when the field is present.
export interface ReliabilityMetrics {
  diagnosis: {
    accepted: number
    rejected: number
    reviewed: number
    acceptance_rate: number | null
    seen?: number
    acceptance_of_seen?: number | null
    review_coverage?: number | null
    by_detector?: Record<string, DetectorDiagnosis>
  }
  remediation: {
    prevented: number
    recurred: number
    inconclusive: number
    verified_outcomes: number
    verified_remediation_rate: number | null
    comparison_cases: number
    baseline_failure_rate: number | null
    post_repair_failure_rate: number | null
    recurrence_reduction: number | null
    recurrence_reduction_note: string
  }
  time_to_applied_workflow_control: {
    sample_size: number
    median_seconds: number | null
    p90_seconds: number | null
  }
  time_to_verified_control?: {
    sample_size: number
    median_seconds: number | null
    p90_seconds: number | null
  }
  durable_controls: {
    applied_workflow_controls: number
    proposed?: number
    applied?: number
    durable?: number
    // Widened from the literal `null` the old server hardcoded: the corrected
    // servers compute a real share (durable / proposed).
    share: number | null
    share_note: string
    by_kind?: Record<'input_schema' | 'error_route' | 'workflow_patch', DurableControlKind>
    harness?: { implemented: boolean; note: string }
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
