'use client'

import Link from 'next/link'
import { ArrowLeft, AlertTriangle, ExternalLink } from 'lucide-react'
import { Layout } from '@/components/common/Layout'
import { Card, CardHeader, CardTitle, Badge, ConfidenceTierBadge, EmptyState } from '@/components/ui'
import { Skeleton } from '@/components/ui/Skeleton'
import { formatConfidencePct } from '@/lib/utils'
import { detectionTypeConfig, plainEnglishLabels, severityConfig } from '@/components/detection/DetectionTypeConfig'
import { FixPanel } from '@/components/detection/FixPanel'
import { GuardPanel } from '@/components/detection/GuardPanel'
import { FeedbackPanel } from '@/components/detection/FeedbackPanel'
import { RepairVerificationPanel } from '@/components/detection/RepairVerificationPanel'
import { TraceView } from '@/components/detection/TraceView'
import { useDetection } from '@/hooks/useDetections'
import { N8N_BASE_URL } from '@/lib/flags'
import { IS_SAAS } from '@/lib/saas'

function confidenceTier(confidence: number): string {
  if (confidence >= 0.8) return 'HIGH'
  if (confidence >= 0.6) return 'LIKELY'
  if (confidence >= 0.4) return 'POSSIBLE'
  return 'LOW'
}

// Plain-English gloss on what a tier means, so the number isn't naked.
const tierMeaning: Record<string, string> = {
  HIGH: 'Strong evidence this failure occurred.',
  LIKELY: 'Good evidence this failure occurred.',
  POSSIBLE: 'Some evidence — worth a look.',
  LOW: 'Weak signal — may be a false positive.',
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs uppercase tracking-wide text-ink-3">{label}</span>
      <span className="text-sm text-ink-2">{value}</span>
    </div>
  )
}

function evidenceLabel(key: string): string {
  return key.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function evidenceValue(value: unknown): string {
  if (Array.isArray(value)) return value.map(evidenceValue).join(', ')
  if (value && typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function EvidenceRecord({ evidence }: { evidence?: Record<string, unknown> }) {
  const entries = Object.entries(evidence ?? {})
  if (!entries.length) return null

  return (
    <Card padding="lg" className="border-rule bg-paper-2">
      <CardHeader className="mb-5">
        <CardTitle>Evidence used</CardTitle>
        <p className="mt-1 text-sm text-ink-3">
          The detector facts retained for this finding. Raw workflow payloads stay local.
        </p>
      </CardHeader>
      <dl className="grid grid-cols-1 gap-x-8 gap-y-4 sm:grid-cols-2">
        {entries.map(([key, value]) => (
          <div key={key} className="min-w-0 border-l border-rule pl-3">
            <dt className="text-xs uppercase tracking-wide text-ink-3">{evidenceLabel(key)}</dt>
            <dd className="mt-1 break-words font-mono text-sm text-ink-2">{evidenceValue(value)}</dd>
          </div>
        ))}
      </dl>
    </Card>
  )
}

export function DetectionDetailClient({ id }: { id: string }) {
  const { data: detection, isLoading, isError, error, refetch } = useDetection(id)
  const notFound = isError && /404/.test((error as Error)?.message ?? '')

  return (
    <Layout title="Detection">
      <div className="mx-auto max-w-3xl space-y-6">
        <Link
          href="/detections"
          className="inline-flex items-center gap-1.5 text-sm text-ink-3 hover:text-ink transition-colors"
        >
          <ArrowLeft size={14} />
          Back to detections
        </Link>

        {isLoading ? (
          <Skeleton className="h-64" />
        ) : notFound ? (
          <Card>
            <EmptyState
              icon={AlertTriangle}
              title="Detection not found"
              description={`No detection with id ${id}.`}
            />
          </Card>
        ) : isError || !detection ? (
          <Card>
            <EmptyState
              icon={AlertTriangle}
              title="Couldn't reach the server"
              description={(error as Error)?.message}
            />
          </Card>
        ) : (
          (() => {
            const typeConfig =
              detectionTypeConfig[detection.detection_type] || detectionTypeConfig.infinite_loop
            const TypeIcon = typeConfig.icon
            const label = plainEnglishLabels[detection.detection_type] || typeConfig.label
            const tier = confidenceTier(detection.confidence)
            const severity =
              severityConfig[detection.details?.severity || 'medium'] || severityConfig.medium
            const workflowLabel = detection.workflow_name || detection.workflow_id || '—'

            // Precise per-execution deep link when we have the workflow + upstream
            // execution id; otherwise fall back to the instance's executions view.
            const base = N8N_BASE_URL.replace(/\/$/, '')
            const precise = detection.workflow_id && detection.n8n_execution_id
            const execUrl = !N8N_BASE_URL
              ? null
              : precise
              ? `${base}/workflow/${detection.workflow_id}/executions/${detection.n8n_execution_id}`
              : `${base}/executions`
            const execLabel = precise ? 'Open this execution in n8n' : 'Open executions in n8n'

            return (
              <>
                <Card padding="lg">
                  <CardHeader className="mb-6">
                    <div className="flex items-center gap-3">
                      <div className="p-2 rounded-lg bg-paper-3/40">
                        <TypeIcon size={20} className={typeConfig.color} />
                      </div>
                      <div className="flex-1">
                        <CardTitle>{label}</CardTitle>
                        <span className="text-xs text-ink-3">{typeConfig.label}</span>
                      </div>
                      <ConfidenceTierBadge tier={tier} />
                    </div>
                  </CardHeader>

                  {/* What happened — the narrative, up top and readable. */}
                  <div className="mb-6">
                    <div className="text-xs uppercase tracking-wide text-ink-3 mb-1.5">
                      What happened
                    </div>
                    <p className="text-sm text-ink-2 leading-relaxed">
                      {detection.business_impact || 'No description available for this detection.'}
                    </p>
                  </div>

                  <div className="grid grid-cols-2 gap-x-6 gap-y-5 pt-5 border-t border-rule">
                    <Field label="Workflow" value={workflowLabel} />
                    <Field label="Detector" value={detection.detection_type} />
                    <Field
                      label="Confidence"
                      value={
                        <span>
                          {formatConfidencePct(detection.confidence)}{' '}
                          <span className="text-ink-3">· {tierMeaning[tier]}</span>
                        </span>
                      }
                    />
                    <Field
                      label="Severity"
                      value={
                        <span className={`px-2 py-0.5 rounded-full text-xs ${severity.bg} ${severity.color}`}>
                          {severity.label}
                        </span>
                      }
                    />
                    <Field label="Failure mode" value={detection.failure_mode ?? '—'} />
                    <Field
                      label="Status"
                      value={
                        <Badge variant={detection.detected ? 'warning' : 'default'} size="sm">
                          {detection.detected ? 'Fired' : 'Clear'}
                        </Badge>
                      }
                    />
                  </div>

                  {execUrl && (
                    <div className="mt-6 pt-5 border-t border-rule">
                      <a
                        href={execUrl}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1.5 text-sm text-evidence hover:underline"
                      >
                        {execLabel}
                        <ExternalLink size={13} />
                      </a>
                    </div>
                  )}
                </Card>

                {detection.detected && <EvidenceRecord evidence={detection.evidence} />}

                <TraceView detectionId={id} />

                {detection.detected && (
                  <FeedbackPanel detectionId={id} initialFeedback={detection.feedback} />
                )}

                {detection.detected && detection.failure_mode === 'n8n_data_contract' ? (
                  IS_SAAS ? (
                    <Card padding="lg">
                      <p className="text-sm text-ink-3">
                        Guardrail repair is available in self-hosted deployments.
                      </p>
                    </Card>
                  ) : (
                    <GuardPanel detectionId={id} onRepairApplied={() => void refetch()} />
                  )
                ) : (
                  detection.detected && (
                    <FixPanel detectionId={id} onRepairApplied={() => void refetch()} />
                  )
                )}

                {detection.reliability_case && (
                  <RepairVerificationPanel
                    initialCase={detection.reliability_case}
                    onUpdated={() => void refetch()}
                  />
                )}
              </>
            )
          })()
        )}
      </div>
    </Layout>
  )
}
