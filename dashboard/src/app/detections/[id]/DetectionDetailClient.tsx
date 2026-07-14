'use client'

import Link from 'next/link'
import { ArrowLeft, AlertTriangle } from 'lucide-react'
import { Layout } from '@/components/common/Layout'
import { Card, CardHeader, CardTitle, Badge, ConfidenceTierBadge, EmptyState } from '@/components/ui'
import { Skeleton } from '@/components/ui/Skeleton'
import { formatConfidencePct } from '@/lib/utils'
import { detectionTypeConfig, plainEnglishLabels } from '@/components/detection/DetectionTypeConfig'
import { useDetections } from '@/hooks/useDetections'

function confidenceTier(confidence: number): string {
  if (confidence >= 0.8) return 'HIGH'
  if (confidence >= 0.6) return 'LIKELY'
  if (confidence >= 0.4) return 'POSSIBLE'
  return 'LOW'
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1 py-3 border-b border-rule last:border-0">
      <span className="text-xs uppercase tracking-wide text-ink-3">{label}</span>
      <span className="text-sm text-ink-2">{value}</span>
    </div>
  )
}

export function DetectionDetailClient({ id }: { id: string }) {
  const { data, isLoading, isError, error } = useDetections()

  const detection = data?.find((d) => d.id === id)

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
        ) : isError ? (
          <Card>
            <EmptyState
              icon={AlertTriangle}
              title="Couldn't reach the server"
              description={(error as Error)?.message}
            />
          </Card>
        ) : !detection ? (
          <Card>
            <EmptyState
              icon={AlertTriangle}
              title="Detection not found"
              description={`No detection with id ${id}.`}
            />
          </Card>
        ) : (
          (() => {
            const typeConfig =
              detectionTypeConfig[detection.detection_type] || detectionTypeConfig.infinite_loop
            const TypeIcon = typeConfig.icon
            const label = plainEnglishLabels[detection.detection_type] || typeConfig.label
            return (
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
                    <ConfidenceTierBadge tier={confidenceTier(detection.confidence)} />
                  </div>
                </CardHeader>

                <Field label="Detector" value={detection.detection_type} />
                <Field
                  label="Confidence"
                  value={`${formatConfidencePct(detection.confidence)}`}
                />
                <Field
                  label="Status"
                  value={
                    <Badge variant={detection.detected ? 'warning' : 'default'} size="sm">
                      {detection.detected ? 'Fired' : 'Clear'}
                    </Badge>
                  }
                />
                <Field label="Failure mode" value={detection.failure_mode ?? '—'} />
                <Field label="Explanation" value={detection.business_impact || '—'} />
                <Field label="Execution" value={`#${detection.trace_id}`} />
              </Card>
            )
          })()
        )}
      </div>
    </Layout>
  )
}
