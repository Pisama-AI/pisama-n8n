'use client'

import { HTMLAttributes, forwardRef } from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const badgeVariants = cva(
  'inline-flex items-center font-medium rounded border',
  {
    variants: {
      variant: {
        default: 'border-rule text-ink-2 bg-paper-2',
        success: 'border-green-500/50 text-green-400 bg-green-500/10',
        warning: 'border-evidence/50 text-evidence bg-amber-500/10',
        error: 'border-red-500/50 text-red-400 bg-red-500/10',
        info: 'border-evidence/50 text-evidence bg-evidence/10',
      },
      size: {
        sm: 'px-2 py-0.5 text-xs',
        md: 'px-2.5 py-0.5 text-xs',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'md',
    },
  }
)

export interface BadgeProps
  extends HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export const Badge = forwardRef<HTMLSpanElement, BadgeProps>(
  ({ className, variant, size, children, ...props }, ref) => {
    return (
      <span
        ref={ref}
        className={cn(badgeVariants({ variant, size }), className)}
        {...props}
      >
        {children}
      </span>
    )
  }
)

Badge.displayName = 'Badge'


const tierConfig: Record<string, { variant: BadgeProps['variant']; label: string }> = {
  HIGH: { variant: 'success', label: 'HIGH' },
  LIKELY: { variant: 'info', label: 'LIKELY' },
  POSSIBLE: { variant: 'warning', label: 'POSSIBLE' },
  LOW: { variant: 'error', label: 'LOW' },
}

export interface ConfidenceTierBadgeProps {
  tier?: string | null
  className?: string
}

export function ConfidenceTierBadge({ tier, className }: ConfidenceTierBadgeProps) {
  if (!tier) return null
  const config = tierConfig[tier.toUpperCase()] ?? { variant: 'default' as const, label: tier }
  return (
    <Badge variant={config.variant} size="sm" className={className}>
      {config.label}
    </Badge>
  )
}
