'use client'

import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
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
export function FixPanel({
  detectionId,
  onRepairApplied,
}: {
  detectionId: string
  onRepairApplied?: () => void
}) {
  const queryClient = useQueryClient()
  const { data: status } = useQuery({ queryKey: ['paid-status'], queryFn: getPaidStatus })
  const [suggestion, setSuggestion] = useState<FixSuggestion | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Apply flow uses a server-owned repair record. The browser never retains the
  // authoritative snapshot or sends workflow JSON back to the server.
  const [applyState, setApplyState] = useState<'idle' | 'confirm' | 'applying' | 'applied'>('idle')

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
    if (!suggestion?.repair_id) {
      setError('This fix proposal is invalid. Generate a new fix.')
      return
    }
    setApplyState('applying')
    setError(null)
    try {
      await applyFix(suggestion.repair_id)
      setApplyState('applied')
      await queryClient.invalidateQueries({ queryKey: ['detection', detectionId] })
      onRepairApplied?.()
    } catch {
      setError('Apply failed. The workflow may have changed; review it and generate a new fix.')
      setApplyState('confirm')
    }
  }

  async function onRollback() {
    if (!suggestion?.repair_id) return
    setApplyState('applying')
    try {
      await rollbackFix(suggestion.repair_id)
      setApplyState('idle')
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
              disabled={!suggestion.repair_id}
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
