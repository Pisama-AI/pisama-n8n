import { type LucideIcon } from 'lucide-react'
import { isValidElement, type ComponentType, type ReactNode } from 'react'

import { cn } from '@/lib/utils'

export interface EmptyStateProps {
  /** Optional Lucide icon component (or any ReactNode) for the visual. */
  icon?: LucideIcon | ReactNode
  /** Headline shown below the icon. */
  title: string
  /** Optional supporting copy below the title. */
  description?: ReactNode
  /** Optional CTA — e.g. a Button. */
  action?: ReactNode
  /** Extra classes for the outer container. */
  className?: string
}

/**
 * Standard empty-state layout used across list views.
 *
 * Replaces the ~15+ ad-hoc copies of:
 *   <div className="text-center py-12 px-4">
 *     <Icon className="w-12 h-12..." /> ...
 *   </div>
 *
 * Keep new empty states using this so we have one styling source of truth.
 */
export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  // isValidElement covers already-rendered JSX; the else branch handles both
  // plain function components and forwardRef objects (typeof === 'object').
  const renderedIcon = icon == null
    ? null
    : isValidElement(icon)
    ? icon
    : (() => {
        const Icon = icon as ComponentType<{ className?: string }>
        return <Icon className="w-12 h-12 text-ink-3" />
      })()

  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center text-center py-12 px-4',
        className,
      )}
    >
      {renderedIcon ? <div className="mb-4">{renderedIcon}</div> : null}
      <h3 className="text-lg font-semibold text-ink">{title}</h3>
      {description ? (
        <p className="mt-2 max-w-md text-sm text-ink-3">{description}</p>
      ) : null}
      {action ? <div className="mt-6">{action}</div> : null}
    </div>
  )
}
