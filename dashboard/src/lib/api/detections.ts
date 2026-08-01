import { API_BASE, fetchApi, postApi, resolveKey } from './client'

// Raw row shape returned by the server's GET /api/v1/detections.
export interface ServerDetection {
  id: number
  execution_id: number
  detector: string
  detected: boolean
  confidence: number
  failure_mode: string | null
  explanation: string
  detector_version?: string | null
  evidence?: Record<string, unknown>
  // Added by the server (join on executions.received_at); may be absent on
  // older rows, so the adapter falls back.
  received_at?: string
  // Workflow context (join on executions). workflow_name/n8n_execution_id are
  // null on legacy rows ingested before those columns existed.
  workflow_id?: string | null
  workflow_name?: string | null
  n8n_execution_id?: string | null
  build_revision?: string | null
  feedback?: DetectionFeedback | null
  evaluation_case?: EvaluationCase | null
  execution_fired_modes?: string[]
  reliability_case?: ReliabilityCase | null
  // When an operator first opened the detail view (servers >= 2026-07-20).
  seen_at?: string | null
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
  detector_version?: string | null
  evidence?: Record<string, unknown>
  workflow_id?: string | null
  workflow_name?: string | null
  n8n_execution_id?: string | null
  build_revision?: string | null
  details?: {
    severity?: string
    affected_agents?: number
  }
  feedback?: DetectionFeedback | null
  evaluation_case?: EvaluationCase | null
  execution_fired_modes: string[]
  reliability_case?: ReliabilityCase | null
}

export type FeedbackVerdict = 'useful' | 'not_useful' | 'fixed_manually'

export interface DetectionFeedback {
  id: number
  detection_id: number
  verdict: FeedbackVerdict
  note: string | null
  actor_principal: string | null
  created_at: string
}

export type EvaluationSplit = 'regression' | 'holdout'

export interface EvaluationCase {
  id: number
  detection_id: number
  execution_id: number
  expected_modes: string[]
  split: EvaluationSplit
  label_evidence: string
  taxonomy_version: string
  feedback_id: number | null
  created_by_principal: string | null
  payload_sha256: string | null
  revision: number
  revision_count: number
  created_at: string
  corpus_case_id: string | null
  corpus_provenance: Record<string, unknown> | null
  source: {
    capture: string
    execution_id: string | null
    workflow_id: string | null
    build_revision: string | null
    detection_id: number
    feedback_id: number | null
    reviewer_principal: string | null
    created_by_principal: string | null
    payload_sha256: string | null
    revision: number
  }
}

export interface EvaluationCaseRevision {
  evaluation_case_id: number
  revision: number
  feedback_id: number | null
  expected_modes: string[]
  split: EvaluationSplit
  label_evidence: string
  taxonomy_version: string
  created_by_principal: string | null
  payload_sha256: string | null
  created_at: string
  reviewer_principal: string | null
}

export interface EvaluationCaseExport {
  schema_version: string
  taxonomy_version: string
  description: string
  cases: Array<Record<string, unknown>>
}

export interface EvaluationScoreCase {
  id: string
  expected_modes: string[]
  actual_modes: string[]
  missing_modes: string[]
  unexpected_modes: string[]
  exact_match: boolean
}

export interface EvaluationSplitScore {
  n: number
  exact_set_matches: number
  exact_set_accuracy: number | null
}

export interface EvaluationScore {
  evaluation_schema_version: string
  taxonomy_version: string
  build_revision: string
  n: number
  exact_set_matches: number
  exact_set_accuracy: number
  micro: { precision: number | null; recall: number | null; f1: number | null }
  macro: { precision: number | null; recall: number | null; f1: number | null }
  per_mode: Record<string, Record<string, number | null>>
  by_split: Record<EvaluationSplit, EvaluationSplitScore>
  cases: EvaluationScoreCase[]
}

export interface EvaluationRunCase {
  evaluation_case_id: number
  case_revision: number
  payload_sha256: string
  split: EvaluationSplit
  expected_modes: string[]
  label_evidence: string
  actual_modes: string[]
  missing_modes: string[]
  unexpected_modes: string[]
  exact_match: boolean | null
}

export interface EvaluationRun {
  id: number
  status: 'pending' | 'running' | 'succeeded' | 'failed'
  taxonomy_version: string
  engine_version: string
  build_revision: string
  requested_by_principal: string
  requested_at: string
  started_at: string | null
  completed_at: string | null
  case_count: number
  protocol_id: number | null
  result: EvaluationScore | null
  error: string | null
  cases: EvaluationRunCase[]
}

export interface ReliabilityCase {
  id: number
  repair_id: number
  detection_id: number
  workflow_id: string
  detector: string
  failure_mode: string | null
  status: 'observing' | 'recurred' | 'prevented' | 'inconclusive' | 'rolled_back' | 'drifted'
  outcome: ReliabilityOutcome | 'recurred' | null
  // Failure-rate window fields — present on an self-host model-fix case; the SaaS
  // guardrail case is focused on the two routing probes and omits them.
  baseline_execution_count?: number
  baseline_failure_count?: number
  post_repair_execution_count?: number
  post_repair_failure_count?: number
  comparison_minimum_executions?: number
  comparison_ready?: boolean
  baseline_failure_rate?: number | null
  post_repair_failure_rate?: number | null
  recurrence_reduction?: number | null
  successful_execution_count?: number
  recurrence_count?: number
  first_success_execution_id?: number | null
  first_recurrence_execution_id?: number | null
  required_successful_executions?: number
  ready_for_outcome_review: boolean
  // Guardrail prevention probes: the two real executions that prove the installed
  // guard rejects malformed input and passes valid input. Present on a guardrail case.
  guard_malformed_rejected_execution_id?: number | null
  guard_valid_passed_execution_id?: number | null
  // Guard drift: the installed guard is no longer present/wired in the live workflow.
  // Set by the server's poll-time integrity sweep; blocks concluding 'prevented'.
  guard_drift_kind?: string | null
  guard_drift_detected_at?: string | null
  guard_drift_note?: string | null
  outcome_note: string | null
  created_at: string
  updated_at: string
  outcome_at: string | null
}

export type ReliabilityOutcome = 'prevented' | 'inconclusive'
export type GuardVerificationKind = 'malformed_rejected' | 'valid_passed'

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
    detector_version: row.detector_version ?? null,
    evidence: row.evidence ?? {},
    workflow_id: row.workflow_id ?? null,
    workflow_name: row.workflow_name ?? null,
    n8n_execution_id: row.n8n_execution_id ?? null,
    build_revision: row.build_revision ?? null,
    feedback: row.feedback ?? null,
    evaluation_case: row.evaluation_case ?? null,
    execution_fired_modes: row.execution_fired_modes ?? [],
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
  verdict: FeedbackVerdict
): Promise<DetectionFeedback> {
  return postApi(`/api/v1/detections/${detectionId}/feedback`, { verdict })
}

export function createEvaluationCase(
  detectionId: string,
  expectedModes: string[],
  split: EvaluationSplit,
  labelEvidence: string
): Promise<EvaluationCase> {
  return postApi(`/api/v1/detections/${detectionId}/evaluation-case`, {
    expected_modes: expectedModes,
    split,
    label_evidence: labelEvidence,
  })
}

export function exportEvaluationCases(): Promise<EvaluationCaseExport> {
  return fetchApi('/api/v1/evaluation-cases/export')
}

export function getEvaluationCases(): Promise<EvaluationCase[]> {
  return fetchApi('/api/v1/evaluation-cases')
}

export function getEvaluationCaseRevisions(caseId: number): Promise<EvaluationCaseRevision[]> {
  return fetchApi(`/api/v1/evaluation-cases/${caseId}/revisions`)
}

export function reviseEvaluationCase(
  caseId: number,
  expectedModes: string[],
  split: EvaluationSplit,
  labelEvidence: string
): Promise<EvaluationCase> {
  return postApi(`/api/v1/evaluation-cases/${caseId}/revisions`, {
    expected_modes: expectedModes,
    split,
    label_evidence: labelEvidence,
  })
}

export function createEvaluationRun(): Promise<EvaluationRun> {
  return postApi('/api/v1/evaluation-runs', {})
}

export function getEvaluationRuns(): Promise<EvaluationRun[]> {
  return fetchApi('/api/v1/evaluation-runs')
}

export function getEvaluationRun(runId: number): Promise<EvaluationRun> {
  return fetchApi(`/api/v1/evaluation-runs/${runId}`)
}

export function concludeReliabilityCase(
  caseId: number,
  outcome: ReliabilityOutcome,
  note?: string
): Promise<ReliabilityCase> {
  return postApi(`/api/v1/reliability-cases/${caseId}/outcome`, {
    outcome,
    note,
  })
}

// A recent execution of the guarded workflow, annotated with how it routed through
// this guard. `matches_kind` flags it as a clean probe for one of the two checks;
// the record endpoint still re-verifies the routing authoritatively.
export interface CandidateExecution {
  execution_id: number
  source_execution_id: string | null
  received_at: string
  destination_ran: boolean
  consumer_ran: boolean
  matches_kind: GuardVerificationKind | null
}

export function getCandidateExecutions(caseId: number): Promise<CandidateExecution[]> {
  return fetchApi(`/api/v1/reliability-cases/${caseId}/candidate-executions`)
}

// Record a guardrail prevention probe against a real ingested execution — referenced by
// its internal id (from the picker) or its n8n source id (manual entry). The server
// verifies the routing from the execution's runData (rejection destination ran + guarded
// consumer skipped for malformed; the inverse for valid) and returns 409 on a mismatch or
// an execution that has not been ingested yet. Same path on the self-host and SaaS servers.
export function recordGuardVerification(
  caseId: number,
  kind: GuardVerificationKind,
  ref: { executionId?: number; sourceExecutionId?: string }
): Promise<ReliabilityCase> {
  return postApi(`/api/v1/reliability-cases/${caseId}/guard-verification`, {
    kind,
    execution_id: ref.executionId,
    source_execution_id: ref.sourceExecutionId,
  })
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

// Fire-and-forget "operator opened the detail view" ping — the sound denominator
// for diagnosis acceptance. Deliberately NOT postApi: a background ping must never
// be able to yank the page to sign-in (postApi's SaaS 401 handler does exactly
// that), and an old server's 404 must be silent. The server is first-timestamp-wins
// idempotent, so duplicate pings are harmless.
export function markDetectionSeen(id: string | number): void {
  const key = resolveKey()
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (key) headers.Authorization = `Bearer ${key}`
  void fetch(`${API_BASE}/api/v1/detections/${id}/seen`, {
    method: 'POST',
    headers,
  }).catch(() => {})
}
