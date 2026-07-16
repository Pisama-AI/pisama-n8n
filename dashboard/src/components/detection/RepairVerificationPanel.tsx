'use client'

import { useEffect, useState } from 'react'
import { AlertTriangle, Check, CircleDot, ShieldCheck } from 'lucide-react'
import { Badge, Button, Card, CardHeader, CardTitle } from '@/components/ui'
import {
  concludeReliabilityCase,
  type ReliabilityCase,
  type ReliabilityOutcome,
} from '@/lib/api/detections'

type PendingOutcome = ReliabilityOutcome | null

function statusVariant(status: ReliabilityCase['status']) {
  if (status === 'prevented') return 'success'
  if (status === 'recurred') return 'error'
  if (status === 'observing') return 'info'
  return 'default'
}

function statusCopy(caseRecord: ReliabilityCase): string {
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
  const progress = Math.min(
    100,
    Math.round((caseRecord.successful_execution_count / caseRecord.required_successful_executions) * 100),
  )
  const comparisonProgress = Math.min(
    100,
    Math.round(
      (caseRecord.post_repair_execution_count / Math.max(1, caseRecord.baseline_execution_count)) * 100,
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

      <div className="mt-5 border-y border-rule py-4">
        <div className="flex items-baseline justify-between gap-4">
          <span className="text-xs uppercase tracking-wide text-ink-3">Post-repair evidence</span>
          <span className="font-mono text-xs text-ink-2">
            {caseRecord.successful_execution_count} / {caseRecord.required_successful_executions} successful
          </span>
        </div>
        <div
          className="mt-2 h-1.5 overflow-hidden rounded-full bg-paper-3"
          role="progressbar"
          aria-valuenow={caseRecord.successful_execution_count}
          aria-valuemin={0}
          aria-valuemax={caseRecord.required_successful_executions}
          aria-label="Successful post-repair executions observed"
        >
          <div className="h-full rounded-full bg-evidence/70" style={{ width: `${progress}%` }} />
        </div>
        <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-xs text-ink-3">
          <span className="inline-flex items-center gap-1.5">
            <Check size={13} className="text-evidence" />
            {caseRecord.successful_execution_count} successful execution{caseRecord.successful_execution_count === 1 ? '' : 's'}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <AlertTriangle size={13} className={caseRecord.recurrence_count ? 'text-red-400' : 'text-ink-4'} />
            {caseRecord.recurrence_count} recurrence{caseRecord.recurrence_count === 1 ? '' : 's'}
          </span>
        </div>
      </div>

      {caseRecord.baseline_execution_count > 0 && (
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
            {caseRecord.comparison_ready && caseRecord.recurrence_reduction !== null
              ? `Observed failure-rate change: ${Math.round(caseRecord.recurrence_reduction * 100)}%.`
              : `Needs ${caseRecord.comparison_minimum_executions} baseline executions and an equal post-repair window before Pisama calculates a rate change.`}
          </p>
        </div>
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
