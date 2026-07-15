import Link from 'next/link'
import { formatDistanceToNow } from 'date-fns'
import { cn } from '@/lib/utils'
import { Wrench } from 'lucide-react'
import { detectionTypeConfig, severityConfig, plainEnglishLabels } from './DetectionTypeConfig'

interface DetectionListItemProps {
  detection: {
    id: string
    detection_type: string
    trace_id: string
    confidence: number
    business_impact?: string
    created_at: string
    details?: {
      severity?: string
    }
  }
}

// Single-tenant n8n dashboard row. Plain-English label + severity + a jump into
// detail. (The monorepo's inline validate / false-positive controls are omitted:
// this product has no human-labeling loop.)
export function DetectionListItem({ detection }: DetectionListItemProps) {
  const typeConfig = detectionTypeConfig[detection.detection_type] || detectionTypeConfig.infinite_loop
  // Backend severities aren't limited to severityConfig's four keys (it also
  // emits "none", "minor", "info", "severe", …). Fall back to the medium style
  // for any unmapped value so an unmapped severity can't throw on `severity.bg`.
  const severity = severityConfig[detection.details?.severity || 'medium'] || severityConfig.medium
  const TypeIcon = typeConfig.icon
  const displayLabel = plainEnglishLabels[detection.detection_type] || typeConfig.label

  return (
    <Link
      href={`/detections/${detection.id}`}
      className="flex items-center gap-4 p-4 hover:bg-paper-3/30 transition-colors"
    >
      <div className={cn('p-2 rounded-lg', severity.bg)}>
        <TypeIcon size={16} className={typeConfig.color} />
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className="font-medium text-ink">{displayLabel}</span>
          <span className={cn('text-xs px-2 py-0.5 rounded-full', severity.bg, severity.color)}>
            {severity.label}
          </span>
        </div>
        <div className="flex items-center gap-4 text-xs text-ink-3">
          <span>{formatDistanceToNow(new Date(detection.created_at), { addSuffix: true })}</span>
          {severity.label !== 'Low' && <span className="text-evidence">Recommended to fix</span>}
        </div>
        {detection.business_impact && (
          <p className="mt-1.5 text-xs text-ink-3 truncate">
            <span className="text-ink-2">Risk:</span> {detection.business_impact}
          </p>
        )}
      </div>

      <div className="text-right">
        {/* Visual affordance only — the whole row is already a Link to the same
            place; a nested <a> would be invalid HTML (hydration error). */}
        <span className="inline-flex items-center gap-1 px-3 py-1.5 text-sm bg-evidence hover:bg-evidence-2 text-evidence-ink rounded-lg transition-colors">
          <Wrench size={14} />
          View
        </span>
      </div>
    </Link>
  )
}
