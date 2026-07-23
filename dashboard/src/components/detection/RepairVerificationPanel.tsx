'use client'

import { useEffect, useState } from 'react'
import { AlertTriangle, Check, CircleDot, ShieldCheck } from 'lucide-react'
import { Badge, Button, Card, CardHeader, CardTitle, Input } from '@/components/ui'
import {
  concludeReliabilityCase,
  getCandidateExecutions,
  recordGuardVerification,
  type CandidateExecution,
  type GuardVerificationKind,
  type ReliabilityCase,
  type ReliabilityOutcome,
} from '@/lib/api/detections'

type PendingOutcome = ReliabilityOutcome | null

// What each drift kind means for the customer, in their terms. Kinds come from the
// server's poll-time integrity sweep (engine assert_guard_still_wired).
const DRIFT_COPY: Record<string, string> = {
  guard_bypassed:
    'Something now feeds the guarded step directly, so input can reach it without passing the guard. Every guard node still exists — only the wiring changed.',
  guard_deleted: 'One or more of the guard’s nodes have been removed from the workflow.',
  guard_detached: 'The guard no longer passes validated input on to the guarded step.',
  rejection_path_broken:
    'Rejected input no longer reaches the destination you chose, so rejections may go nowhere.',
}

function statusVariant(status: ReliabilityCase['status']) {
  if (status === 'prevented') return 'success'
  if (status === 'recurred' || status === 'drifted') return 'error'
  if (status === 'observing') return 'info'
  return 'default'
}

function statusCopy(caseRecord: ReliabilityCase): string {
  if (caseRecord.status === 'drifted') {
    return 'This guard is no longer protecting the workflow — it was changed or removed in n8n after Pisama applied it. Until it is restored, this repair is not preventing anything.'
  }
  if (caseRecord.status === 'recurred') {
    return 'The same failure pattern appeared again after this repair. Review the repair before relying on it.'
  }
  if (caseRecord.status === 'prevented') {
    return 'Your team concluded that this repair prevented recurrence. The underlying execution evidence remains local.'
  }
  if (caseRecord.status === 'inconclusive') {
    return 'Your team recorded that the available evidence was not enough to conclude whether this repair prevented recurrence.'
  }
  if (caseRecord.status === 'rolled_back') {
    return caseRecord.outcome
      ? `This repair was rolled back. Its recorded outcome was ${caseRecord.outcome}.`
      : 'This repair was rolled back. The verification record remains available for the audit trail.'
  }
  return 'Pisama is collecting later real executions. A successful run shows exposure after the change, not prevention by itself.'
}

// The two prevention probes a guardrail must pass. Each is recorded against a REAL
// n8n execution: the operator fires the described input at their workflow, then enters
// the resulting n8n execution id; the server verifies the routing from its runData.
const GUARD_PROBES: {
  kind: GuardVerificationKind
  label: string
  hint: string
}[] = [
  {
    kind: 'malformed_rejected',
    label: 'Malformed input rejected',
    hint: 'Send input that is MISSING a required field. The guard should reject it (the rejection destination runs, your original node is skipped).',
  },
  {
    kind: 'valid_passed',
    label: 'Valid input passed through',
    hint: 'Send WELL-FORMED input. The guard should pass it through to your original workflow logic.',
  },
]

function shortTime(iso: string): string {
  const m = iso.match(/(\d{4})-(\d{2})-(\d{2})T(\d{2}:\d{2})/)
  return m ? `${m[2]}-${m[3]} ${m[4]}` : iso
}

function routingLabel(c: CandidateExecution): string {
  if (c.matches_kind === 'malformed_rejected') return 'guard rejected'
  if (c.matches_kind === 'valid_passed') return 'passed through'
  if (c.destination_ran && c.consumer_ran) return 'both ran'
  return 'no guard routing'
}

// Interactive guard-verification for a guardrail repair. The operator picks the probe
// execution from a routing-annotated list of the workflow's recent runs (or types an id
// manually); the server re-verifies the real routing and refuses a mismatch (409).
function GuardVerificationSection({
  caseRecord,
  onRecorded,
}: {
  caseRecord: ReliabilityCase
  onRecorded: (updated: ReliabilityCase) => void
}) {
  const [openKind, setOpenKind] = useState<GuardVerificationKind | null>(null)
  const [candidates, setCandidates] = useState<CandidateExecution[] | null>(null)
  const [loadingCandidates, setLoadingCandidates] = useState(false)
  const [manualId, setManualId] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const recorded: Record<GuardVerificationKind, boolean> = {
    malformed_rejected: caseRecord.guard_malformed_rejected_execution_id != null,
    valid_passed: caseRecord.guard_valid_passed_execution_id != null,
  }
  const concluded = caseRecord.status !== 'observing'

  async function openRecorder(kind: GuardVerificationKind) {
    setOpenKind(kind)
    setManualId('')
    setError(null)
    if (candidates === null && !loadingCandidates) {
      setLoadingCandidates(true)
      try {
        setCandidates(await getCandidateExecutions(caseRecord.id))
      } catch {
        setCandidates([]) // fair-code server or fetch error → manual entry only
      } finally {
        setLoadingCandidates(false)
      }
    }
  }

  async function submit(kind: GuardVerificationKind, ref: { executionId?: number; sourceExecutionId?: string }) {
    setSaving(true)
    setError(null)
    try {
      onRecorded(await recordGuardVerification(caseRecord.id, kind, ref))
      setOpenKind(null)
      setManualId('')
      setCandidates(null) // the just-used execution should re-annotate on the next open
    } catch (caught) {
      const status = (caught as Error & { status?: number }).status
      setError(
        status === 409
          ? 'That execution did not show the expected routing (or has not been ingested yet). Fire the described input, let Pisama poll it, then pick it again.'
          : 'Could not record the probe. Check your server connection and try again.',
      )
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="mt-4 border-t border-rule pt-4">
      <span className="text-xs uppercase tracking-wide text-ink-3">Guard verification</span>
      <p className="mt-1 text-xs leading-relaxed text-ink-3">
        Prove the installed guard works with two real executions. A guardrail can be concluded
        prevented only once both checks are observed.
      </p>
      <div className="mt-3 space-y-3">
        {GUARD_PROBES.map((probe) => {
          const done = recorded[probe.kind]
          const open = openKind === probe.kind
          const ranked = candidates
            ? [...candidates].sort(
                (a, b) => Number(b.matches_kind === probe.kind) - Number(a.matches_kind === probe.kind),
              )
            : []
          return (
            <div key={probe.kind}>
              <div className="flex items-center gap-2 text-sm text-ink-2">
                {done ? (
                  <Check size={14} className="shrink-0 text-evidence" />
                ) : (
                  <CircleDot size={14} className="shrink-0 text-ink-4" />
                )}
                <span>{probe.label}</span>
                {done ? (
                  <span className="text-xs text-ink-4">recorded</span>
                ) : (
                  !concluded && !open && (
                    <Button variant="ghost" size="sm" onClick={() => void openRecorder(probe.kind)}>
                      Record
                    </Button>
                  )
                )}
              </div>
              {!done && open && (
                <div className="mt-2 space-y-2 rounded-lg border border-rule bg-paper-3/30 p-3">
                  <p className="text-xs leading-relaxed text-ink-3">{probe.hint}</p>
                  {loadingCandidates ? (
                    <p className="text-xs text-ink-4">Loading recent executions…</p>
                  ) : ranked.length > 0 ? (
                    <ul className="space-y-1">
                      {ranked.map((c) => {
                        const suggested = c.matches_kind === probe.kind
                        return (
                          <li key={c.execution_id}>
                            <button
                              type="button"
                              disabled={saving}
                              onClick={() => void submit(probe.kind, { executionId: c.execution_id })}
                              className={`flex w-full items-center justify-between gap-3 rounded border px-2 py-1.5 text-left text-xs transition-colors hover:bg-paper-2 disabled:opacity-50 ${
                                suggested ? 'border-evidence/50 bg-evidence/5' : 'border-rule'
                              }`}
                            >
                              <span className="font-mono text-ink-2">
                                {c.source_execution_id ?? `#${c.execution_id}`}
                              </span>
                              <span className="flex items-center gap-2 text-ink-4">
                                <span>{shortTime(c.received_at)}</span>
                                <span className={suggested ? 'text-evidence' : ''}>{routingLabel(c)}</span>
                              </span>
                            </button>
                          </li>
                        )
                      })}
                    </ul>
                  ) : (
                    <p className="text-xs text-ink-4">
                      No recent executions of this workflow yet. Fire the described input, let
                      Pisama poll it, then reopen — or enter its n8n execution id below.
                    </p>
                  )}
                  <div className="flex flex-wrap items-center gap-2 pt-1">
                    <Input
                      value={manualId}
                      onChange={(e) => setManualId(e.target.value)}
                      placeholder="or n8n execution id"
                      className="max-w-[180px]"
                    />
                    <Button
                      variant="secondary"
                      size="sm"
                      isLoading={saving}
                      disabled={!manualId.trim()}
                      onClick={() => void submit(probe.kind, { sourceExecutionId: manualId.trim() })}
                      leftIcon={<ShieldCheck size={14} />}
                    >
                      Verify
                    </Button>
                    <Button variant="ghost" size="sm" disabled={saving} onClick={() => setOpenKind(null)}>
                      Cancel
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>
      {error && <p className="mt-2 text-xs leading-relaxed text-red-400">{error}</p>}
    </div>
  )
}

export function RepairVerificationPanel({
  initialCase,
  onUpdated,
}: {
  initialCase: ReliabilityCase
  onUpdated?: () => void
}) {
  const [caseRecord, setCaseRecord] = useState(initialCase)
  const [pending, setPending] = useState<PendingOutcome>(null)
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    setCaseRecord(initialCase)
  }, [initialCase])

  // A guardrail case is verified by the two routing probes, not the failure-rate window.
  const isGuardrail = caseRecord.failure_mode === 'n8n_data_contract'
  // The failure-rate window only exists on an self-host model-fix case (SaaS omits it).
  const hasFailureWindow = caseRecord.required_successful_executions != null
  const successful = caseRecord.successful_execution_count ?? 0
  const required = caseRecord.required_successful_executions ?? 0
  const progress = required > 0 ? Math.min(100, Math.round((successful / required) * 100)) : 0
  const comparisonProgress = Math.min(
    100,
    Math.round(
      ((caseRecord.post_repair_execution_count ?? 0) /
        Math.max(1, caseRecord.baseline_execution_count ?? 0)) *
        100,
    ),
  )

  async function record(outcome: ReliabilityOutcome) {
    setSaving(true)
    setError(null)
    try {
      setCaseRecord(await concludeReliabilityCase(caseRecord.id, outcome, note || undefined))
      setPending(null)
      onUpdated?.()
    } catch (caught) {
      const status = (caught as Error & { status?: number }).status
      setError(
        status === 409
          ? 'The evidence changed or this case is already concluded. Refresh and review it again.'
          : 'Could not record the conclusion. Check your server connection and try again.',
      )
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card padding="lg">
      <CardHeader className="mb-4">
        <div className="flex items-center gap-2">
          <ShieldCheck size={16} className="text-evidence" />
          <CardTitle>Repair verification</CardTitle>
          <Badge variant={statusVariant(caseRecord.status)} size="sm">
            {caseRecord.status}
          </Badge>
        </div>
      </CardHeader>

      <p className="text-sm leading-relaxed text-ink-2">{statusCopy(caseRecord)}</p>

      {caseRecord.status === 'drifted' && (
        <div className="mt-4 rounded-lg border border-red-400/40 bg-red-400/5 p-3">
          <div className="flex items-center gap-2">
            <AlertTriangle size={14} className="shrink-0 text-red-400" />
            <span className="text-xs font-semibold uppercase tracking-wide text-red-400">
              Guard no longer active
            </span>
            {caseRecord.guard_drift_detected_at && (
              <span className="ml-auto font-mono text-xs text-ink-4">
                since {shortTime(caseRecord.guard_drift_detected_at)}
              </span>
            )}
          </div>
          <p className="mt-2 text-xs leading-relaxed text-ink-2">
            {DRIFT_COPY[caseRecord.guard_drift_kind ?? ''] ??
              'The installed guard no longer matches what Pisama applied.'}
          </p>
          {caseRecord.guard_drift_note && (
            <p className="mt-1.5 font-mono text-xs leading-relaxed text-ink-3">
              {caseRecord.guard_drift_note}
            </p>
          )}
          <p className="mt-2 text-xs leading-relaxed text-ink-3">
            Re-apply the guard from this detection to restore protection. This case cannot be
            concluded as prevention while the guard is inactive.
          </p>
        </div>
      )}

      {hasFailureWindow && (
        <div className="mt-5 border-y border-rule py-4">
          <div className="flex items-baseline justify-between gap-4">
            <span className="text-xs uppercase tracking-wide text-ink-3">Post-repair evidence</span>
            <span className="font-mono text-xs text-ink-2">
              {successful} / {required} successful
            </span>
          </div>
          <div
            className="mt-2 h-1.5 overflow-hidden rounded-full bg-paper-3"
            role="progressbar"
            aria-valuenow={successful}
            aria-valuemin={0}
            aria-valuemax={required}
            aria-label="Successful post-repair executions observed"
          >
            <div className="h-full rounded-full bg-evidence/70" style={{ width: `${progress}%` }} />
          </div>
          <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-xs text-ink-3">
            <span className="inline-flex items-center gap-1.5">
              <Check size={13} className="text-evidence" />
              {successful} successful execution{successful === 1 ? '' : 's'}
            </span>
            <span className="inline-flex items-center gap-1.5">
              <AlertTriangle size={13} className={caseRecord.recurrence_count ? 'text-red-400' : 'text-ink-4'} />
              {caseRecord.recurrence_count ?? 0} recurrence{(caseRecord.recurrence_count ?? 0) === 1 ? '' : 's'}
            </span>
          </div>
        </div>
      )}

      {(caseRecord.baseline_execution_count ?? 0) > 0 && (
        <div className="mt-4">
          <div className="flex items-baseline justify-between gap-4">
            <span className="text-xs uppercase tracking-wide text-ink-3">Comparable failure-rate window</span>
            <span className="font-mono text-xs text-ink-2">
              {caseRecord.post_repair_execution_count} / {caseRecord.baseline_execution_count} post-repair
            </span>
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-paper-3">
            <div className="h-full rounded-full bg-ink-3/50" style={{ width: `${comparisonProgress}%` }} />
          </div>
          <p className="mt-2 text-xs leading-relaxed text-ink-3">
            {caseRecord.comparison_ready && caseRecord.recurrence_reduction != null
              ? `Observed failure-rate change: ${Math.round(caseRecord.recurrence_reduction * 100)}%.`
              : `Needs ${caseRecord.comparison_minimum_executions} baseline executions and an equal post-repair window before Pisama calculates a rate change.`}
          </p>
        </div>
      )}

      {isGuardrail && (
        <GuardVerificationSection
          caseRecord={caseRecord}
          onRecorded={(updated) => {
            setCaseRecord(updated)
            onUpdated?.()
          }}
        />
      )}

      {caseRecord.status === 'observing' && (
        <div className="mt-5 space-y-3">
          {pending ? (
            <>
              <label className="block text-xs uppercase tracking-wide text-ink-3" htmlFor={`outcome-note-${caseRecord.id}`}>
                Review note (optional)
              </label>
              <textarea
                id={`outcome-note-${caseRecord.id}`}
                value={note}
                onChange={(event) => setNote(event.target.value)}
                maxLength={1000}
                rows={2}
                className="w-full resize-y rounded border border-rule bg-paper-3 px-3 py-2 text-sm text-ink placeholder:text-ink-4 focus:border-evidence focus:outline-none"
                placeholder="Why is this conclusion justified?"
              />
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  variant={pending === 'prevented' ? 'success' : 'secondary'}
                  size="sm"
                  isLoading={saving}
                  onClick={() => record(pending)}
                  leftIcon={pending === 'prevented' ? <ShieldCheck size={14} /> : <CircleDot size={14} />}
                >
                  {pending === 'prevented' ? 'Record prevention' : 'Record inconclusive'}
                </Button>
                <Button variant="ghost" size="sm" disabled={saving} onClick={() => setPending(null)}>
                  Cancel
                </Button>
              </div>
            </>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              {caseRecord.ready_for_outcome_review && (
                <Button
                  variant="success"
                  size="sm"
                  leftIcon={<ShieldCheck size={14} />}
                  onClick={() => setPending('prevented')}
                >
                  Conclude prevention
                </Button>
              )}
              <Button
                variant="ghost"
                size="sm"
                leftIcon={<CircleDot size={14} />}
                onClick={() => setPending('inconclusive')}
              >
                Mark inconclusive
              </Button>
            </div>
          )}
        </div>
      )}

      {caseRecord.outcome_note && (
        <p className="mt-4 border-l-2 border-rule pl-3 text-sm leading-relaxed text-ink-3">
          {caseRecord.outcome_note}
        </p>
      )}
      {error && <p className="mt-3 text-sm text-red-400">{error}</p>}
    </Card>
  )
}
