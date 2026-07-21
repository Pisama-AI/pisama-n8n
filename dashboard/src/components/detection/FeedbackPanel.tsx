'use client'

import { useState } from 'react'
import { Check, ThumbsDown, ThumbsUp, Wrench } from 'lucide-react'
import { Button, Card, CardHeader, CardTitle } from '@/components/ui'
import {
  submitDetectionFeedback,
  type DetectionFeedback,
  type FeedbackVerdict,
} from '@/lib/api/detections'

const options: Array<{ verdict: FeedbackVerdict; label: string; icon: typeof ThumbsUp }> = [
  { verdict: 'useful', label: 'Useful finding', icon: ThumbsUp },
  { verdict: 'not_useful', label: 'Not useful', icon: ThumbsDown },
  { verdict: 'fixed_manually', label: 'Fixed manually', icon: Wrench },
]

export function FeedbackPanel({
  detectionId,
  initialFeedback,
}: {
  detectionId: string
  initialFeedback?: DetectionFeedback | null
}) {
  const [feedback, setFeedback] = useState(initialFeedback ?? null)
  const [saving, setSaving] = useState<FeedbackVerdict | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function submit(verdict: FeedbackVerdict) {
    setSaving(verdict)
    setError(null)
    try {
      setFeedback(await submitDetectionFeedback(detectionId, verdict))
    } catch {
      setError('Could not save feedback. Check your server connection and try again.')
    } finally {
      setSaving(null)
    }
  }

  return (
    <Card padding="lg">
      <CardHeader className="mb-3">
        <CardTitle>Was this useful?</CardTitle>
      </CardHeader>
      <p className="text-sm text-ink-3 mb-4">
        Your verdict stays in this server and helps your team measure detector quality.
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
      {error && <p className="mt-3 text-sm" style={{ color: 'var(--fail)' }}>{error}</p>}
    </Card>
  )
}
