'use client'

import {
  forwardRef,
  Children,
  cloneElement,
  isValidElement,
  type CSSProperties,
  type HTMLAttributes,
  type ReactElement,
  type ReactNode,
} from 'react'
import { cn } from '@/lib/utils'

// CSS-driven entrance animations. Replaces framer-motion (which pulled
// ~40-60KB gzipped into the dashboard bundle) with keyframes defined in
// globals.css (pa-fade-in / pa-scale-in). The public API (FadeIn /
// StaggerContainer / StaggerItem / ScaleIn) is unchanged so consumers keep
// working as-is. prefers-reduced-motion is honored globally by the reduce
// block in globals.css.

type DivProps = HTMLAttributes<HTMLDivElement>

// Fade in from below — for page content.
export const FadeIn = forwardRef<HTMLDivElement, DivProps & { delay?: number }>(
  ({ delay = 0, className, style, children, ...props }, ref) => (
    <div
      ref={ref}
      className={cn('pa-fade-in', className)}
      style={delay ? { ...style, animationDelay: `${delay}s` } : style}
      {...props}
    >
      {children}
    </div>
  )
)

FadeIn.displayName = 'FadeIn'

// Stagger container — animates its direct children in sequence. Each direct
// element child is tagged with --pa-stagger-index; the per-step delay comes
// from --pa-stagger-step, which StaggerItem reads via inheritance.
export function StaggerContainer({
  children,
  className,
  stagger = 0.05,
}: {
  children: ReactNode
  className?: string
  stagger?: number
}) {
  let index = 0
  return (
    <div
      className={className}
      style={{ '--pa-stagger-step': `${stagger}s` } as CSSProperties}
    >
      {Children.map(children, child => {
        if (!isValidElement(child)) return child
        const el = child as ReactElement<{ style?: CSSProperties }>
        return cloneElement(el, {
          style: { ...el.props.style, '--pa-stagger-index': index++ } as CSSProperties,
        })
      })}
    </div>
  )
}

// Stagger item — use as a direct child of StaggerContainer.
export const StaggerItem = forwardRef<HTMLDivElement, DivProps>(
  ({ className, children, ...props }, ref) => (
    <div ref={ref} className={cn('pa-stagger-item', className)} {...props}>
      {children}
    </div>
  )
)

StaggerItem.displayName = 'StaggerItem'

// Scale in — for modals and popups.
export const ScaleIn = forwardRef<HTMLDivElement, DivProps>(
  ({ className, children, ...props }, ref) => (
    <div ref={ref} className={cn('pa-scale-in', className)} {...props}>
      {children}
    </div>
  )
)

ScaleIn.displayName = 'ScaleIn'
