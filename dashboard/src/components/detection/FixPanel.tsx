'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Wrench, Sparkles, Lock } from 'lucide-react'
import { Card, CardHeader, CardTitle, Button } from '@/components/ui'
import { getPaidStatus, requestFix, type FixSuggestion } from '@/lib/api/fixes'

// The paid-tier affordance: request an AI-generated fix from the Pisama cloud. Shown as a
// locked upsell when the server has no cloud key; a live "Get fix" when it does.
export function FixPanel({ detectionId }: { detectionId: string }) {
  const { data: status } = useQuery({ queryKey: ['paid-status'], queryFn: getPaidStatus })
  const [suggestion, setSuggestion] = useState<FixSuggestion | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const enabled = status?.enabled ?? false

  async function onGetFix() {
    setLoading(true)
    setError(null)
    try {
      setSuggestion(await requestFix(detectionId))
    } catch (e) {
      const status = (e as Error & { status?: number }).status
      setError(status === 402 ? 'Fix suggestions are a paid feature.' : 'Fix request failed.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Card padding="lg">
      <CardHeader className="mb-4">
        <div className="flex items-center gap-2">
          <Sparkles size={16} className="text-evidence" />
          <CardTitle>Suggested fix</CardTitle>
          {!enabled && (
            <span className="ml-2 inline-flex items-center gap-1 text-xs text-ink-3">
              <Lock size={12} /> paid
            </span>
          )}
        </div>
      </CardHeader>

      {!enabled ? (
        <p className="text-sm text-ink-3">
          AI fix suggestions and one-click auto-apply are part of the Pisama cloud tier.
          Configure <code className="text-ink-2">PISAMA_CLOUD_KEY</code> on the server to enable.
        </p>
      ) : suggestion ? (
        <div className="space-y-4">
          <p className="text-sm text-ink-2">{suggestion.explanation}</p>
          <div className="rounded-lg border border-rule bg-paper-3/30 p-3">
            <div className="text-xs uppercase tracking-wide text-ink-3 mb-2">Proposed change</div>
            {suggestion.patch_ops.map((op, i) => (
              <div key={i} className="font-mono text-xs text-ink-2">
                set {op.target}
                {op.node ? ` · ${op.node}` : ''} · {op.key} = {JSON.stringify(op.value)}
              </div>
            ))}
          </div>
          <Button variant="primary" size="sm" leftIcon={<Wrench size={14} />} disabled>
            Apply to n8n (approve)
          </Button>
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-ink-3">
            Ask Pisama to generate a targeted fix for this failure.
          </p>
          <Button variant="primary" size="sm" onClick={onGetFix} isLoading={loading}
                  leftIcon={<Wrench size={14} />}>
            Get fix
          </Button>
          {error && <p className="text-sm text-fail">{error}</p>}
        </div>
      )}
    </Card>
  )
}
