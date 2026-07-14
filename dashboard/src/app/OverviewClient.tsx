'use client'

import { Activity, AlertTriangle, Radar } from 'lucide-react'
import { Layout } from '@/components/common/Layout'
import { StatCard } from '@/components/detection/StatCard'
import { Card, EmptyState } from '@/components/ui'
import { Skeleton } from '@/components/ui/Skeleton'
import { useDetections } from '@/hooks/useDetections'

export function OverviewClient() {
  const { data, isLoading, isError, error } = useDetections()

  const detections = data ?? []
  const fired = detections.filter((d) => d.detected)
  const executionsAnalyzed = new Set(detections.map((d) => d.trace_id)).size
  const detectorsReporting = new Set(detections.map((d) => d.detection_type)).size

  return (
    <Layout title="Overview">
      <div className="mx-auto max-w-5xl space-y-6">
        <div>
          <h2 className="font-serif text-2xl text-ink">Failure detection</h2>
          <p className="text-sm text-ink-3 mt-1">
            Self-hosted analysis of your n8n workflow executions.
          </p>
        </div>

        {isLoading ? (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <Skeleton className="h-20" />
            <Skeleton className="h-20" />
            <Skeleton className="h-20" />
          </div>
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
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <StatCard
              icon={Activity}
              label="Executions analyzed"
              value={executionsAnalyzed}
              color="text-evidence"
              bgColor="bg-evidence/10 border border-rule"
            />
            <StatCard
              icon={AlertTriangle}
              label="Detections fired"
              value={fired.length}
              color="text-orange-400"
              bgColor="bg-orange-500/20"
            />
            <StatCard
              icon={Radar}
              label="Detectors reporting"
              value={detectorsReporting}
              color="text-green-400"
              bgColor="bg-green-500/20"
            />
          </div>
        )}
      </div>
    </Layout>
  )
}
