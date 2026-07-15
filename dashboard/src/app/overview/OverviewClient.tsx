'use client'

import Link from 'next/link'
import { Activity, AlertTriangle, Percent } from 'lucide-react'
import { format, startOfDay, subDays, isSameDay, formatDistanceToNow } from 'date-fns'
import { Layout } from '@/components/common/Layout'
import { StatCard } from '@/components/detection/StatCard'
import { Card, CardHeader, CardTitle, EmptyState } from '@/components/ui'
import { Skeleton } from '@/components/ui/Skeleton'
import { useDetections } from '@/hooks/useDetections'
import {
  detectionTypeConfig,
  plainEnglishLabels,
} from '@/components/detection/DetectionTypeConfig'
import type { Detection } from '@/lib/api/detections'

const TREND_DAYS = 14
const BAR_AREA_PX = 128 // chart height in px; explicit so bar heights don't rely on % of a flex parent

// Fired detections per day for the last N days. Pure CSS bars — no chart dep.
function FailuresOverTime({ fired }: { fired: Detection[] }) {
  const today = startOfDay(new Date())
  const days = Array.from({ length: TREND_DAYS }, (_, i) =>
    subDays(today, TREND_DAYS - 1 - i),
  )
  const counts = days.map(
    (day) => fired.filter((d) => isSameDay(new Date(d.created_at), day)).length,
  )
  const max = Math.max(1, ...counts)

  return (
    <Card padding="lg">
      <CardHeader className="mb-4">
        <CardTitle>Failures over time</CardTitle>
        <p className="text-xs text-ink-3 mt-1">Detections fired, last {TREND_DAYS} days</p>
      </CardHeader>
      <div
        className="flex items-end gap-1.5"
        style={{ height: BAR_AREA_PX }}
        role="img"
        aria-label={`Failures per day over the last ${TREND_DAYS} days`}
      >
        {days.map((day, i) => {
          const h = counts[i] > 0 ? Math.max(4, (counts[i] / max) * BAR_AREA_PX) : 2
          return (
            <div
              key={i}
              className="flex-1 flex items-end h-full"
              title={`${format(day, 'MMM d')}: ${counts[i]} fired`}
            >
              <div
                className={`w-full rounded-sm ${counts[i] > 0 ? 'bg-evidence' : 'bg-rule'}`}
                style={{ height: h }}
              />
            </div>
          )
        })}
      </div>
      <div className="flex justify-between mt-2 text-[10px] text-ink-4 font-mono">
        <span>{format(days[0], 'MMM d')}</span>
        <span>{format(days[days.length - 1], 'MMM d')}</span>
      </div>
    </Card>
  )
}

// Fired detections grouped by detector type, most common first.
function ByType({ fired }: { fired: Detection[] }) {
  const counts = new Map<string, number>()
  for (const d of fired) counts.set(d.detection_type, (counts.get(d.detection_type) ?? 0) + 1)
  const rows = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6)
  const max = Math.max(1, ...rows.map(([, n]) => n))

  return (
    <Card padding="lg">
      <CardHeader className="mb-4">
        <CardTitle>Most common failures</CardTitle>
        <p className="text-xs text-ink-3 mt-1">By detector, across analyzed executions</p>
      </CardHeader>
      {rows.length === 0 ? (
        <p className="text-sm text-ink-3">No failures detected yet.</p>
      ) : (
        <div className="space-y-3">
          {rows.map(([type, n]) => {
            const cfg = detectionTypeConfig[type] || detectionTypeConfig.infinite_loop
            const label = plainEnglishLabels[type] || cfg.label
            const Icon = cfg.icon
            return (
              <div key={type} className="flex items-center gap-3">
                <Icon size={15} className={cfg.color} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-sm text-ink-2 truncate">{label}</span>
                    <span className="text-xs text-ink-3 font-mono ml-2">{n}</span>
                  </div>
                  <div className="h-1.5 rounded-full bg-paper-3 overflow-hidden">
                    <div
                      className="h-full rounded-full bg-evidence/70"
                      style={{ width: `${(n / max) * 100}%` }}
                    />
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </Card>
  )
}

// The five most recent fired detections, each a link into detail.
function RecentActivity({ fired }: { fired: Detection[] }) {
  const recent = [...fired]
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, 5)

  return (
    <Card padding="none">
      <CardHeader className="mb-0 p-6 pb-4">
        <CardTitle>Recent activity</CardTitle>
      </CardHeader>
      {recent.length === 0 ? (
        <p className="text-sm text-ink-3 px-6 pb-6">No detections yet.</p>
      ) : (
        <div className="divide-y divide-rule">
          {recent.map((d) => {
            const cfg = detectionTypeConfig[d.detection_type] || detectionTypeConfig.infinite_loop
            const label = plainEnglishLabels[d.detection_type] || cfg.label
            const Icon = cfg.icon
            return (
              <Link
                key={d.id}
                href={`/detections/${d.id}`}
                className="flex items-center gap-3 px-6 py-3 hover:bg-paper-3/30 transition-colors"
              >
                <Icon size={15} className={cfg.color} />
                <span className="flex-1 text-sm text-ink-2 truncate">{label}</span>
                <span className="text-xs text-ink-4 font-mono">Exec #{d.trace_id}</span>
                <span className="text-xs text-ink-3 w-24 text-right">
                  {formatDistanceToNow(new Date(d.created_at), { addSuffix: true })}
                </span>
              </Link>
            )
          })}
        </div>
      )}
    </Card>
  )
}

export function OverviewClient() {
  const { data, isLoading, isError, error } = useDetections()

  const detections = data ?? []
  const fired = detections.filter((d) => d.detected)
  const executionsAnalyzed = new Set(detections.map((d) => d.trace_id)).size
  const executionsFailed = new Set(fired.map((d) => d.trace_id)).size
  const failureRate = executionsAnalyzed
    ? Math.round((executionsFailed / executionsAnalyzed) * 100)
    : 0

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
          <>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <Skeleton className="h-20" />
              <Skeleton className="h-20" />
              <Skeleton className="h-20" />
            </div>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <Skeleton className="h-52" />
              <Skeleton className="h-52" />
            </div>
          </>
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
          <>
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
                icon={Percent}
                label="Executions with a failure"
                value={`${failureRate}%`}
                color="text-evidence"
                bgColor="bg-evidence/10 border border-rule"
              />
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <FailuresOverTime fired={fired} />
              <ByType fired={fired} />
            </div>

            <RecentActivity fired={fired} />
          </>
        )}
      </div>
    </Layout>
  )
}
