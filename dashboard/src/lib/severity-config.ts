/**
 * Canonical severity → presentation mapping for Pisama frontend.
 *
 * Used for the standard label / color / bg / Badge variant triple. Some
 * components (ImprovementCard, QualitySuggestionsCard, DiagnosisResults)
 * keep their own local config because they diverge intentionally — they
 * either include an icon, an info-tier severity, a description string,
 * or use a different palette (violet vs amber/orange).
 */

import type { BadgeProps } from '@/components/ui/Badge'

export type Severity = 'critical' | 'high' | 'medium' | 'low'

export interface SeverityStyle {
  label: string
  variant: BadgeProps['variant']
  color: string
  bg: string
}

export const severityConfig: Record<string, SeverityStyle> = {
  critical: { label: 'Critical', variant: 'error', color: 'text-red-400', bg: 'bg-red-500/20' },
  high: { label: 'High', variant: 'warning', color: 'text-orange-400', bg: 'bg-orange-500/20' },
  medium: { label: 'Medium', variant: 'info', color: 'text-amber-400', bg: 'bg-amber-500/20' },
  low: { label: 'Low', variant: 'default', color: 'text-zinc-400', bg: 'bg-zinc-500/20' },
}
