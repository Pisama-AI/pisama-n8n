'use client'

import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ShieldPlus, Check, Undo2, Wrench, AlertTriangle } from 'lucide-react'
import { Card, CardHeader, CardTitle, Button, Input } from '@/components/ui'
import {
  proposeGuardrail,
  setGuardrailDestination,
  applyGuardrail,
  rollbackGuardrail,
  type ProposeGuardrailResponse,
  type SetGuardrailDestinationResponse,
  type GuardDestinationKind,
} from '@/lib/api/guardrail'

const DESTINATION_SENTENCE: Record<GuardDestinationKind, string> = {
  error_workflow: 'Malformed input is rejected and routed to the error workflow.',
  alert: 'Malformed input is rejected and an alert is sent to the configured URL.',
  respond_422: 'Malformed input is rejected and the caller receives a 422 response.',
}

function errorMessage(e: unknown, fallback: string): string {
  const err = e as Error & { status?: number }
  return err?.message || fallback
}

// Operator UI for the deterministic input-schema guardrail repair (fair-code self-host
// AND multi-tenant SaaS). Flow: propose -> pick/confirm required paths -> pick
// destination -> preview the generated subgraph -> apply (with the same
// confirm/rollback affordance as FixPanel). In SaaS, apply is Pro-gated (402).
export function GuardPanel({
  detectionId,
  onRepairApplied,
}: {
  detectionId: string
  onRepairApplied?: () => void
}) {
  const queryClient = useQueryClient()
  const [proposal, setProposal] = useState<ProposeGuardrailResponse | null>(null)
  const [selectedPaths, setSelectedPaths] = useState<string[]>([])
  const [destination, setDestination] = useState<GuardDestinationKind | null>(null)
  const [alertUrl, setAlertUrl] = useState('')
  const [preview, setPreview] = useState<SetGuardrailDestinationResponse['repair'] | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [applyState, setApplyState] = useState<'idle' | 'confirm' | 'applying' | 'applied'>('idle')

  const id = Number(detectionId)

  async function onPropose(paths?: string[]) {
    setLoading(true)
    setError(null)
    try {
      const res = await proposeGuardrail(id, paths)
      setProposal(res)
      const initial = res.path_options.confirmed.length
        ? res.path_options.confirmed
        : res.path_options.candidates
      setSelectedPaths(initial)
      setPreview(null)
      setDestination(null)
      setApplyState('idle')
    } catch (e) {
      setError(errorMessage(e, 'Guardrail proposal failed.'))
    } finally {
      setLoading(false)
    }
  }

  function togglePath(path: string) {
    setSelectedPaths((prev) =>
      prev.includes(path) ? prev.filter((p) => p !== path) : [...prev, path],
    )
  }

  async function onConfirmPaths() {
    if (!proposal) return
    const confirmed = proposal.path_options.confirmed
    const diverged =
      confirmed.length !== selectedPaths.length ||
      !confirmed.every((p) => selectedPaths.includes(p))
    if (!diverged) return
    await onPropose(selectedPaths)
  }

  async function onSetDestination() {
    if (!proposal || !destination) return
    setLoading(true)
    setError(null)
    try {
      const res = await setGuardrailDestination(
        proposal.repair.id,
        destination,
        destination === 'alert' ? alertUrl : undefined,
      )
      setPreview(res.repair)
    } catch (e) {
      setError(errorMessage(e, 'Could not set the destination for this guardrail.'))
    } finally {
      setLoading(false)
    }
  }

  async function onApply() {
    if (!proposal) return
    setApplyState('applying')
    setError(null)
    try {
      await applyGuardrail(proposal.repair.id)
      setApplyState('applied')
      await queryClient.invalidateQueries({ queryKey: ['detection', detectionId] })
      onRepairApplied?.()
    } catch (e) {
      const status = (e as { status?: number }).status
      setError(
        status === 402
          ? 'Installing a guardrail requires the Pro plan. Upgrade to enable remediation.'
          : errorMessage(e, 'Apply failed. Review the workflow and propose the guardrail again.'),
      )
      setApplyState('confirm')
    }
  }

  async function onRollback() {
    if (!proposal) return
    setApplyState('applying')
    try {
      await rollbackGuardrail(proposal.repair.id)
      setApplyState('idle')
    } catch {
      setError('Rollback failed.')
      setApplyState('applied')
    }
  }

  const candidatesOnly =
    proposal && proposal.path_options.confirmed.length === 0 && proposal.path_options.candidates.length > 0
  const pathsDiverged =
    proposal &&
    (proposal.path_options.confirmed.length !== selectedPaths.length ||
      !proposal.path_options.confirmed.every((p) => selectedPaths.includes(p)))

  return (
    <Card padding="lg">
      <CardHeader className="mb-4">
        <div className="flex items-center gap-2">
          <ShieldPlus size={16} className="text-evidence" />
          <CardTitle>Input-schema guardrail</CardTitle>
        </div>
      </CardHeader>

      {!proposal ? (
        <div className="space-y-3">
          <p className="text-sm text-ink-3">
            Pisama can add a deterministic guard in front of the failing node that rejects
            malformed input before it reaches your workflow logic.
          </p>
          <Button variant="primary" size="sm" onClick={() => onPropose()} isLoading={loading}
                  leftIcon={<ShieldPlus size={14} />}>
            Propose guard
          </Button>
          {error && <p className="text-sm" style={{ color: 'var(--fail)' }}>{error}</p>}
        </div>
      ) : (
        <div className="space-y-5">
          <div className="rounded-lg border border-rule bg-paper-3/30 p-3 space-y-2">
            <div className="text-xs uppercase tracking-wide text-ink-3">Required paths</div>
            <p className="text-xs text-ink-3">
              {candidatesOnly
                ? 'No confirmed input paths were found. Review the candidates below and select the ones the guard should require.'
                : 'Derived from the failing execution. Uncheck any path that should not be required.'}
            </p>
            <div className="space-y-1.5">
              {[...proposal.path_options.confirmed, ...proposal.path_options.candidates].map((path) => (
                <label key={path} className="flex items-center gap-2 text-sm text-ink-2">
                  <input
                    type="checkbox"
                    checked={selectedPaths.includes(path)}
                    onChange={() => togglePath(path)}
                    className="rounded border-rule"
                  />
                  <code className="font-mono text-xs text-ink">{path}</code>
                  {proposal.path_options.candidates.includes(path) &&
                    !proposal.path_options.confirmed.includes(path) && (
                      <span className="text-xs text-ink-4">candidate</span>
                    )}
                </label>
              ))}
            </div>
            {pathsDiverged && (
              <Button variant="secondary" size="sm" onClick={onConfirmPaths} isLoading={loading}>
                Update paths
              </Button>
            )}
          </div>

          {!preview && (
            <div className="rounded-lg border border-rule bg-paper-3/30 p-3 space-y-2">
              <div className="text-xs uppercase tracking-wide text-ink-3">Destination for rejected input</div>
              <div className="space-y-2">
                {proposal.destinations.map((d) => (
                  <label
                    key={d.kind}
                    className={`flex items-start gap-2 text-sm ${d.available ? 'text-ink-2' : 'text-ink-4'}`}
                  >
                    <input
                      type="radio"
                      name="guard-destination"
                      disabled={!d.available}
                      checked={destination === d.kind}
                      onChange={() => setDestination(d.kind)}
                      className="mt-0.5"
                    />
                    <span>
                      {d.label}
                      {!d.available && d.reason && (
                        <span className="block text-xs text-ink-4">{d.reason}</span>
                      )}
                    </span>
                  </label>
                ))}
              </div>
              {destination === 'alert' && (
                <Input
                  type="url"
                  placeholder="https://example.com/alert-webhook"
                  value={alertUrl}
                  onChange={(e) => setAlertUrl(e.target.value)}
                  required
                />
              )}
              <Button
                variant="primary"
                size="sm"
                onClick={onSetDestination}
                isLoading={loading}
                disabled={!destination || (destination === 'alert' && !alertUrl)}
              >
                Set destination
              </Button>
            </div>
          )}

          {preview?.guard_config && (
            <div className="rounded-lg border border-rule bg-paper-3/30 p-3 space-y-2">
              <div className="text-xs uppercase tracking-wide text-ink-3">Proposed subgraph</div>
              <ul className="space-y-1">
                {preview.proposed_workflow.nodes
                  .filter((n) => preview.guard_config.fragment_node_names?.includes(n.name))
                  .map((n) => (
                    <li key={n.name} className="flex items-center gap-2 text-sm text-ink-2">
                      <span className="font-mono text-xs px-1.5 py-0.5 rounded bg-paper-2 border border-rule text-ink-3">
                        {n.name}
                      </span>
                      <code className="font-mono text-xs text-ink-4">{n.type}</code>
                    </li>
                  ))}
              </ul>
              {preview.guard_config.destination && (
                <p className="text-sm text-ink-2">
                  Valid input continues to the original workflow logic.{' '}
                  {DESTINATION_SENTENCE[preview.guard_config.destination]}
                </p>
              )}

              {applyState === 'applied' ? (
                <div className="flex items-center gap-3">
                  <span className="inline-flex items-center gap-1.5 text-sm" style={{ color: 'var(--pass)' }}>
                    <Check size={15} /> Applied to your n8n workflow
                  </span>
                  <Button variant="ghost" size="sm" onClick={onRollback} leftIcon={<Undo2 size={14} />}>
                    Roll back
                  </Button>
                </div>
              ) : applyState === 'confirm' ? (
                <div className="flex items-center gap-3">
                  <span className="text-sm text-ink-3">Apply this guard to your live workflow?</span>
                  <Button variant="primary" size="sm" onClick={onApply} leftIcon={<Wrench size={14} />}>
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
                  onClick={() => setApplyState('confirm')}
                >
                  Apply to n8n
                </Button>
              )}
            </div>
          )}

          {error && (
            <p className="flex items-start gap-1.5 text-sm" style={{ color: 'var(--fail)' }}>
              <AlertTriangle size={14} className="mt-0.5 shrink-0" />
              {error}
            </p>
          )}
        </div>
      )}
    </Card>
  )
}
