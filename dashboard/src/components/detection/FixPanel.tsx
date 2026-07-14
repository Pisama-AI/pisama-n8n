'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Wrench, Sparkles, Lock, Check, Undo2 } from 'lucide-react'
import { Card, CardHeader, CardTitle, Button } from '@/components/ui'
import {
  getPaidStatus,
  requestFix,
  applyFix,
  rollbackFix,
  type FixSuggestion,
} from '@/lib/api/fixes'

// The paid-tier affordance: request an AI-generated fix from the Pisama cloud. Shown as a
// locked upsell when the server has no cloud key; a live "Get fix" when it does.
export function FixPanel({ detectionId }: { detectionId: string }) {
  const { data: status } = useQuery({ queryKey: ['paid-status'], queryFn: getPaidStatus })
  const [suggestion, setSuggestion] = useState<FixSuggestion | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // apply flow: 'idle' → 'confirm' → 'applying' → 'applied' (holds the snapshot for rollback)
  const [applyState, setApplyState] = useState<'idle' | 'confirm' | 'applying' | 'applied'>('idle')
  const [snapshot, setSnapshot] = useState<Record<string, unknown> | null>(null)

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

  async function onApply() {
    if (!suggestion?.workflow_id) {
      setError('No n8n workflow id — configure PISAMA_N8N_URL/KEY on the server.')
      return
    }
    setApplyState('applying')
    setError(null)
    try {
      const result = await applyFix(suggestion.workflow_id, suggestion.mutated_workflow)
      setSnapshot(result.snapshot)
      setApplyState('applied')
    } catch {
      setError('Apply failed — check the server has n8n API access.')
      setApplyState('confirm')
    }
  }

  async function onRollback() {
    if (!suggestion?.workflow_id || !snapshot) return
    setApplyState('applying')
    try {
      await rollbackFix(suggestion.workflow_id, snapshot)
      setApplyState('idle')
      setSnapshot(null)
    } catch {
      setError('Rollback failed.')
      setApplyState('applied')
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
          {applyState === 'applied' ? (
            <div className="flex items-center gap-3">
              <span className="inline-flex items-center gap-1.5 text-sm" style={{ color: 'var(--pass)' }}>
                <Check size={15} /> Applied to your n8n workflow
              </span>
              <Button variant="ghost" size="sm" onClick={onRollback}
                      leftIcon={<Undo2 size={14} />}>
                Roll back
              </Button>
            </div>
          ) : applyState === 'confirm' ? (
            <div className="flex items-center gap-3">
              <span className="text-sm text-ink-3">Apply this change to your live workflow?</span>
              <Button variant="primary" size="sm" onClick={onApply}
                      isLoading={false} leftIcon={<Wrench size={14} />}>
                Confirm apply
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setApplyState('idle')}>
                Cancel
              </Button>
            </div>
          ) : (
            <Button
              variant="primary"
              size="sm"
              leftIcon={<Wrench size={14} />}
              isLoading={applyState === 'applying'}
              disabled={!suggestion.workflow_id}
              onClick={() => setApplyState('confirm')}
            >
              Apply to n8n
            </Button>
          )}
          {error && <p className="text-sm" style={{ color: 'var(--fail)' }}>{error}</p>}
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
          {error && <p className="text-sm" style={{ color: 'var(--fail)' }}>{error}</p>}
        </div>
      )}
    </Card>
  )
}
