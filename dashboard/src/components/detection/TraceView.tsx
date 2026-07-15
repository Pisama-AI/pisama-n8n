'use client'

import { Card, CardHeader, CardTitle } from '@/components/ui'
import { Skeleton } from '@/components/ui/Skeleton'
import { useDetectionTrace } from '@/hooks/useDetections'
import type { TraceNode } from '@/lib/api/detections'

// n8n node types are namespaced; show the readable tail (e.g. "httpRequest").
function prettyType(type: string | null): string | null {
  if (!type) return null
  return type
    .replace(/^@n8n\/n8n-nodes-langchain\./, '')
    .replace(/^n8n-nodes-base\./, '')
    .replace(/^n8n-nodes-/, '')
}

function fmtMs(ms: number | null): string {
  if (ms == null) return '—'
  if (ms < 1000) return `${ms}ms`
  // Keep seconds up to 2 min so a 64s node reads "64.0s" (matching the
  // detection copy) rather than "1.1m".
  if (ms < 120_000) return `${(ms / 1000).toFixed(1)}s`
  return `${(ms / 60_000).toFixed(1)}m`
}

const DOT: Record<string, string> = {
  success: 'var(--pass)',
  error: 'var(--fail)',
  unknown: 'var(--ink-4)',
}

function StatusPill({ status }: { status: 'success' | 'error' | null | undefined }) {
  if (!status) return null
  const color = status === 'error' ? 'var(--fail)' : 'var(--pass)'
  return (
    <span
      className="inline-flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded border"
      style={{ color, borderColor: color }}
    >
      {status}
    </span>
  )
}

function NodeRow({
  node,
  emphasizeTime,
  emphasizeItems,
}: {
  node: TraceNode
  emphasizeTime: boolean
  emphasizeItems: boolean
}) {
  const type = prettyType(node.type)
  const isError = node.status === 'error'
  return (
    <div
      className="flex items-start gap-3 px-4 py-3"
      style={isError ? { background: 'var(--fail-bg)' } : undefined}
    >
      <span
        aria-hidden
        className="mt-1.5 w-2 h-2 rounded-full shrink-0"
        style={{ background: DOT[node.status] ?? DOT.unknown }}
      />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm text-ink truncate">{node.name}</span>
          {type && <span className="font-mono text-[11px] text-ink-4">{type}</span>}
          {node.runs > 1 && (
            <span className="font-mono text-[10px] text-ink-3">×{node.runs}</span>
          )}
        </div>
        {node.error && (
          <p className="mt-1 text-xs" style={{ color: 'var(--fail)' }}>
            {node.error}
          </p>
        )}
      </div>
      {node.ran && (
        <div className="text-right shrink-0 text-xs">
          <div
            className="font-mono"
            style={{ color: emphasizeTime ? 'var(--evidence)' : 'var(--ink-3)' }}
          >
            {fmtMs(node.execution_time_ms)}
          </div>
          {node.items_out != null && (
            <div
              className="font-mono mt-0.5"
              style={{ color: emphasizeItems ? 'var(--evidence)' : 'var(--ink-4)' }}
            >
              {node.items_out} {node.items_out === 1 ? 'item' : 'items'}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function TraceView({ detectionId }: { detectionId: string }) {
  const { data, isLoading } = useDetectionTrace(detectionId)

  if (isLoading) return <Skeleton className="h-40" />
  if (!data?.available || !data.nodes?.length) {
    return (
      <Card padding="lg">
        <CardHeader className="mb-2">
          <CardTitle>Execution trace</CardTitle>
        </CardHeader>
        <p className="text-sm text-ink-3">No execution trace was stored for this detection.</p>
      </Card>
    )
  }

  const nodes = data.nodes
  // Draw the eye to the outlier node — usually the culprit for timeout/resource.
  const ran = nodes.filter((n) => n.ran)
  const maxTime = ran.reduce((m, n) => Math.max(m, n.execution_time_ms ?? 0), 0)
  const maxItems = ran.reduce((m, n) => Math.max(m, n.items_out ?? 0), 0)
  const summary =
    data.kind === 'runtime'
      ? `${data.node_count} nodes${data.duration_ms != null ? ` · ${fmtMs(data.duration_ms)}` : ''}`
      : `Workflow structure · ${data.node_count} nodes`

  return (
    <Card padding="none">
      <CardHeader className="mb-0 p-6 pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <CardTitle>Execution trace</CardTitle>
            {data.kind === 'runtime' && <StatusPill status={data.status} />}
          </div>
          <span className="text-xs text-ink-3">{summary}</span>
        </div>
      </CardHeader>

      {data.error && (
        <div className="mx-6 mb-3 rounded-lg border p-3 text-sm" style={{ borderColor: 'var(--fail)', color: 'var(--fail)', background: 'var(--fail-bg)' }}>
          {data.error}
        </div>
      )}

      <div className="divide-y divide-rule border-t border-rule">
        {nodes.map((n, i) => (
          <NodeRow
            key={`${n.name}-${i}`}
            node={n}
            emphasizeTime={ran.length > 1 && maxTime > 0 && n.execution_time_ms === maxTime}
            emphasizeItems={ran.length > 1 && maxItems > 1 && n.items_out === maxItems}
          />
        ))}
      </div>

      {data.last_node && (
        <div className="px-6 py-3 text-xs text-ink-4 border-t border-rule">
          Last node executed: <span className="text-ink-3">{data.last_node}</span>
        </div>
      )}
    </Card>
  )
}
