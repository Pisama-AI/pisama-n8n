'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Wrench, Sparkles, Lock, Check, Undo2, ArrowRight } from 'lucide-react'
import { Card, CardHeader, CardTitle, Button } from '@/components/ui'
import {
  getPaidStatus,
  requestFix,
  applyFix,
  rollbackFix,
  startCheckout,
  type FixSuggestion,
  type PatchOp,
} from '@/lib/api/fixes'
import { IS_SAAS } from '@/lib/saas'
import { HEALING_APPLY_ENABLED, BILLING_ENABLED } from '@/lib/flags'

// Render a single patch op as a human-readable line instead of a raw
// `set target · node · key = value` dump. n8n param names (op.key) stay in
// mono because that's exactly how the user sees them inside n8n.
function formatValue(value: unknown): string {
  if (typeof value === 'string') return value.length > 60 ? `${value.slice(0, 57)}…` : value
  return JSON.stringify(value)
}

function ProposedChange({ ops }: { ops: PatchOp[] }) {
  return (
    <div className="rounded-lg border border-rule bg-paper-3/30 p-3 space-y-2">
      <div className="text-xs uppercase tracking-wide text-ink-3">Proposed change</div>
      {ops.map((op, i) => (
        <div key={i} className="flex flex-wrap items-center gap-1.5 text-sm text-ink-2">
          {op.node && (
            <span className="font-mono text-xs px-1.5 py-0.5 rounded bg-paper-2 border border-rule text-ink-3">
              {op.node}
            </span>
          )}
          <span>set</span>
          <code className="font-mono text-xs text-ink">{op.key}</code>
          <ArrowRight size={12} className="text-ink-4" />
          <code className="font-mono text-xs text-evidence">{formatValue(op.value)}</code>
        </div>
      ))}
    </div>
  )
}

// The paid-tier affordance: request an AI-generated fix from the Pisama cloud. Shown as a
// locked upsell when the server has no cloud key; a live "Get fix" when it does. Applying
// the fix to the live workflow is gated behind HEALING_APPLY_ENABLED (default off) so an
// unproven fix can't mutate a customer's production workflow by default.
export function FixPanel({ detectionId }: { detectionId: string }) {
  const { data: status } = useQuery({ queryKey: ['paid-status'], queryFn: getPaidStatus })
  const [suggestion, setSuggestion] = useState<FixSuggestion | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // apply flow: 'idle' → 'confirm' → 'applying' → 'applied' (holds the snapshot for rollback)
  const [applyState, setApplyState] = useState<'idle' | 'confirm' | 'applying' | 'applied'>('idle')
  const [snapshot, setSnapshot] = useState<Record<string, unknown> | null>(null)

  const enabled = status?.enabled ?? false
  // Public showcase (n8n.pisama.ai) runs read-only: no bearer key ships to the browser, so
  // the interactive Get-fix / Apply calls would 401. In that mode we describe the paid
  // capability honestly instead of rendering buttons that error for anonymous visitors.
  const readOnly = process.env.NEXT_PUBLIC_READONLY === '1'

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

      {readOnly ? (
        <p className="text-sm text-ink-3">
          On the self-hosted server, Pisama generates a targeted fix for this failure and shows
          the exact change to make in your n8n workflow. This is a live public demo, so fix
          generation is read-only here.{' '}
          <a href="https://github.com/Pisama-AI/pisama-n8n" className="text-evidence hover:underline">
            Self-host it
          </a>{' '}
          to enable fixes with your own key.
        </p>
      ) : !enabled ? (
        IS_SAAS && BILLING_ENABLED ? (
          <div className="space-y-3">
            <p className="text-sm text-ink-3">
              Pisama can generate a targeted fix for this failure and show you the exact change to
              make. AI fixes are part of Pisama Pro.
            </p>
            <Button
              variant="primary"
              size="sm"
              isLoading={loading}
              leftIcon={<Sparkles size={14} />}
              onClick={async () => {
                setLoading(true)
                setError(null)
                try {
                  window.location.href = await startCheckout()
                } catch {
                  setError('Could not start checkout. Try again.')
                  setLoading(false)
                }
              }}
            >
              Upgrade to Pro
            </Button>
            {error && <p className="text-sm" style={{ color: 'var(--fail)' }}>{error}</p>}
          </div>
        ) : IS_SAAS ? (
          <p className="text-sm text-ink-3">
            AI-generated fixes are part of Pisama Pro. This capability is not yet enabled on your
            plan.
          </p>
        ) : (
          <p className="text-sm text-ink-3">
            AI fix suggestions are part of the Pisama cloud tier. Configure{' '}
            <code className="text-ink-2">PISAMA_CLOUD_KEY</code> on the server to enable.
          </p>
        )
      ) : suggestion ? (
        <div className="space-y-4">
          <p className="text-sm text-ink-2">{suggestion.explanation}</p>
          <ProposedChange ops={suggestion.patch_ops} />

          {/* Write-side (mutate the live workflow) is gated. Default: show the fix as
              guidance the user applies themselves. Flag on: the full apply/rollback flow. */}
          {!HEALING_APPLY_ENABLED ? (
            <p className="text-xs text-ink-3">
              Review this change and apply it in your n8n workflow. One-click auto-apply with
              snapshot and rollback is available when enabled on the server.
            </p>
          ) : applyState === 'applied' ? (
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
