'use client'

import { useState } from 'react'
import { Check, Download, FlaskConical, ThumbsDown, ThumbsUp, Wrench } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { Card, CardHeader, CardTitle } from '@/components/ui/Card'
import {
  createEvaluationCase,
  exportEvaluationCases,
  submitDetectionFeedback,
  type DetectionFeedback,
  type EvaluationCase,
  type EvaluationSplit,
  type FeedbackVerdict,
} from '@/lib/api/detections'

const options: Array<{ verdict: FeedbackVerdict; label: string; icon: typeof ThumbsUp }> = [
  { verdict: 'useful', label: 'Useful finding', icon: ThumbsUp },
  { verdict: 'not_useful', label: 'Not useful', icon: ThumbsDown },
  { verdict: 'fixed_manually', label: 'Fixed manually', icon: Wrench },
]

const fieldClass =
  'w-full rounded border border-rule bg-paper px-3 py-2 text-sm text-ink-2 placeholder:text-ink-4 focus:border-evidence'

function parseModes(value: string): string[] {
  return [...new Set(value.split(',').map((mode) => mode.trim()).filter(Boolean))]
}

export function FeedbackPanel({
  detectionId,
  initialFeedback,
  initialEvaluationCase,
  suggestedModes,
  onUpdated,
}: {
  detectionId: string
  initialFeedback?: DetectionFeedback | null
  initialEvaluationCase?: EvaluationCase | null
  suggestedModes: string[]
  onUpdated?: () => void
}) {
  const [feedback, setFeedback] = useState(initialFeedback ?? null)
  const [evaluationCase, setEvaluationCase] = useState(initialEvaluationCase ?? null)
  const [saving, setSaving] = useState<FeedbackVerdict | null>(null)
  const [savingCase, setSavingCase] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [modeText, setModeText] = useState(suggestedModes.join(', '))
  const [split, setSplit] = useState<EvaluationSplit>('regression')
  const [evidence, setEvidence] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function submit(verdict: FeedbackVerdict) {
    setSaving(verdict)
    setError(null)
    try {
      setFeedback(await submitDetectionFeedback(detectionId, verdict))
      onUpdated?.()
    } catch {
      setError('Could not save feedback. Check your server connection and try again.')
    } finally {
      setSaving(null)
    }
  }

  async function promote() {
    if (!evidence.trim()) {
      setError('Describe the n8n evidence used to confirm these labels.')
      return
    }
    setSavingCase(true)
    setError(null)
    try {
      const created = await createEvaluationCase(
        detectionId,
        parseModes(modeText),
        split,
        evidence.trim(),
      )
      setEvaluationCase(created)
      onUpdated?.()
    } catch {
      setError('Could not freeze this evaluation case. Check the modes and try again.')
    } finally {
      setSavingCase(false)
    }
  }

  async function download() {
    setDownloading(true)
    setError(null)
    try {
      const manifest = await exportEvaluationCases()
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(manifest, null, 2)], { type: 'application/json' }),
      )
      const link = document.createElement('a')
      link.href = url
      link.download = `pisama-evaluation-taxonomy-v${manifest.taxonomy_version}.json`
      link.click()
      URL.revokeObjectURL(url)
    } catch {
      setError('Could not export evaluation cases. Check your server connection.')
    } finally {
      setDownloading(false)
    }
  }

  return (
    <Card padding="lg">
      <CardHeader className="mb-3">
        <CardTitle>Review and evaluation</CardTitle>
      </CardHeader>
      <p className="mb-4 text-sm text-ink-3">
        Your verdict and labels stay in this server. Raw retained executions are
        credential-redacted before export.
      </p>
      {feedback ? (
        <div className="inline-flex items-center gap-2 text-sm text-ink-2">
          <Check size={15} className="text-evidence" />
          Recorded: {options.find((option) => option.verdict === feedback.verdict)?.label}
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          {options.map(({ verdict, label, icon: Icon }) => (
            <Button
              key={verdict}
              variant="ghost"
              size="sm"
              leftIcon={<Icon size={14} />}
              isLoading={saving === verdict}
              disabled={saving !== null}
              onClick={() => submit(verdict)}
            >
              {label}
            </Button>
          ))}
        </div>
      )}

      {feedback && evaluationCase && (
        <div className="mt-5 border-t border-rule pt-5">
          <div className="flex items-start gap-2 text-sm text-ink-2">
            <FlaskConical size={16} className="mt-0.5 text-evidence" />
            <div>
              <div>Evaluation case frozen in {evaluationCase.split}.</div>
              <div className="mt-1 font-mono text-xs text-ink-3">
                {evaluationCase.expected_modes.join(', ') || 'No failure mode expected'} · taxonomy v
                {evaluationCase.taxonomy_version}
              </div>
            </div>
          </div>
          <Button
            className="mt-4"
            variant="ghost"
            size="sm"
            leftIcon={<Download size={14} />}
            isLoading={downloading}
            onClick={download}
          >
            Export evaluation set
          </Button>
        </div>
      )}

      {feedback && !evaluationCase && (
        <div className="mt-5 space-y-4 border-t border-rule pt-5">
          <div>
            <div className="text-sm font-medium text-ink">Freeze as an evaluation case</div>
            <p className="mt-1 text-xs leading-relaxed text-ink-3">
              Pisama suggested the modes fired on this execution. Verify them against n8n,
              remove false positives, and add any missed taxonomy modes.
            </p>
          </div>
          <label className="block text-xs text-ink-3" htmlFor={`evaluation-modes-${detectionId}`}>
            Confirmed failure modes, comma separated
            <input
              id={`evaluation-modes-${detectionId}`}
              className={`${fieldClass} mt-1.5 font-mono`}
              value={modeText}
              onChange={(event) => setModeText(event.target.value)}
              placeholder="Leave empty when no Pisama mode is correct"
            />
          </label>
          <label className="block text-xs text-ink-3" htmlFor={`evaluation-split-${detectionId}`}>
            Evaluation split
            <select
              id={`evaluation-split-${detectionId}`}
              className={`${fieldClass} mt-1.5`}
              value={split}
              onChange={(event) => setSplit(event.target.value as EvaluationSplit)}
            >
              <option value="regression">Regression</option>
              <option value="holdout">Holdout, label before detector changes</option>
            </select>
          </label>
          <label className="block text-xs text-ink-3" htmlFor={`evaluation-evidence-${detectionId}`}>
            Independent n8n label evidence
            <textarea
              id={`evaluation-evidence-${detectionId}`}
              className={`${fieldClass} mt-1.5 min-h-20 resize-y`}
              value={evidence}
              onChange={(event) => setEvidence(event.target.value)}
              placeholder="Example: n8n recorded a TypeError on Set Outputs; workflow settings has no errorWorkflow."
            />
          </label>
          <Button
            size="sm"
            leftIcon={<FlaskConical size={14} />}
            isLoading={savingCase}
            onClick={promote}
          >
            Freeze evaluation case
          </Button>
        </div>
      )}

      {error && <p className="mt-3 text-sm" style={{ color: 'var(--fail)' }}>{error}</p>}
    </Card>
  )
}
