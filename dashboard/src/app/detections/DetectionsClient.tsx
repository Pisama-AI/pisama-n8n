'use client'

import { useMemo, useState } from 'react'
import { ShieldCheck, AlertTriangle, Search } from 'lucide-react'
import { Layout } from '@/components/common/Layout'
import { DetectionListItem } from '@/components/detection/DetectionListItem'
import { Card, EmptyState } from '@/components/ui'
import { Skeleton } from '@/components/ui/Skeleton'
import { useDetections } from '@/hooks/useDetections'
import { plainEnglishLabels, detectionTypeConfig } from '@/components/detection/DetectionTypeConfig'

type SortKey = 'newest' | 'oldest' | 'confidence'

const selectClass =
  'rounded-lg border border-rule bg-paper-2 px-3 py-1.5 text-sm text-ink-2 focus:outline-none focus:border-evidence'

export function DetectionsClient() {
  const { data, isLoading, isError, error } = useDetections()
  const [type, setType] = useState<string>('all')
  const [sort, setSort] = useState<SortKey>('newest')

  const fired = useMemo(() => (data ?? []).filter((d) => d.detected), [data])

  // Detector types actually present, for the filter dropdown.
  const presentTypes = useMemo(() => {
    const set = new Set(fired.map((d) => d.detection_type))
    return [...set].sort()
  }, [fired])

  const shown = useMemo(() => {
    const filtered = type === 'all' ? fired : fired.filter((d) => d.detection_type === type)
    const sorted = [...filtered].sort((a, b) => {
      if (sort === 'confidence') return b.confidence - a.confidence
      const cmp = new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
      return sort === 'newest' ? -cmp : cmp
    })
    return sorted
  }, [fired, type, sort])

  return (
    <Layout title="Detections">
      <div className="mx-auto max-w-4xl space-y-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h2 className="font-serif text-2xl text-ink">Detections</h2>
            <p className="text-sm text-ink-3 mt-1">
              Failures found across your analyzed n8n executions.
            </p>
          </div>
          {fired.length > 0 && (
            <div className="flex items-center gap-2">
              <select
                aria-label="Filter by type"
                className={selectClass}
                value={type}
                onChange={(e) => setType(e.target.value)}
              >
                <option value="all">All types</option>
                {presentTypes.map((t) => (
                  <option key={t} value={t}>
                    {plainEnglishLabels[t] || detectionTypeConfig[t]?.label || t}
                  </option>
                ))}
              </select>
              <select
                aria-label="Sort"
                className={selectClass}
                value={sort}
                onChange={(e) => setSort(e.target.value as SortKey)}
              >
                <option value="newest">Newest first</option>
                <option value="oldest">Oldest first</option>
                <option value="confidence">Strongest evidence</option>
              </select>
            </div>
          )}
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
        ) : shown.length === 0 ? (
          <Card>
            <EmptyState
              icon={Search}
              title="No matches"
              description="No detections match this filter. Try a different type."
            />
          </Card>
        ) : (
          <Card className="p-0 divide-y divide-rule">
            {shown.map((detection) => (
              <DetectionListItem key={detection.id} detection={detection} />
            ))}
          </Card>
        )}
      </div>
    </Layout>
  )
}
