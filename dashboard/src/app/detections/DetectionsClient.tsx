'use client'

import { ShieldCheck, AlertTriangle } from 'lucide-react'
import { Layout } from '@/components/common/Layout'
import { DetectionListItem } from '@/components/detection/DetectionListItem'
import { Card, EmptyState } from '@/components/ui'
import { Skeleton } from '@/components/ui/Skeleton'
import { useDetections } from '@/hooks/useDetections'

export function DetectionsClient() {
  const { data, isLoading, isError, error } = useDetections()

  const fired = (data ?? []).filter((d) => d.detected)

  return (
    <Layout title="Detections">
      <div className="mx-auto max-w-4xl space-y-6">
        <div>
          <h2 className="font-serif text-2xl text-ink">Detections</h2>
          <p className="text-sm text-ink-3 mt-1">
            Failures found across your analyzed n8n executions.
          </p>
        </div>

        {isLoading ? (
          <Card className="p-0">
            <Skeleton className="h-20 m-4" />
            <Skeleton className="h-20 m-4" />
          </Card>
        ) : isError ? (
          <Card>
            <EmptyState
              icon={AlertTriangle}
              title="Couldn't reach the server"
              description={
                (error as Error)?.message ??
                'Check that the pisama-n8n server is running and NEXT_PUBLIC_API_BASE is set.'
              }
            />
          </Card>
        ) : fired.length === 0 ? (
          <Card>
            <EmptyState
              icon={ShieldCheck}
              title="No detections"
              description="No failures have been detected in your analyzed executions yet."
            />
          </Card>
        ) : (
          <Card className="p-0 divide-y divide-rule">
            {fired.map((detection) => (
              <DetectionListItem
                key={detection.id}
                detection={detection}
                showSimplifiedView={true}
                inlineValidated={{}}
                submittingId={null}
                onInlineValidate={() => {}}
              />
            ))}
          </Card>
        )}
      </div>
    </Layout>
  )
}
