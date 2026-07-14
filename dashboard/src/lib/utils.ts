import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'
import type { KeyboardEvent } from 'react'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Keyboard activation handler for elements given `role="button"` (or any
 * non-native clickable div/row). Mirrors native button semantics: Enter and
 * Space fire the handler (and Space's default page-scroll is suppressed).
 * Pair with `tabIndex={0}` plus an `aria-*` label so keyboard users reach
 * parity with mouse users. Factors out the inline pattern in
 * DemoScenarioSelector so every clickable row keeps the same behavior.
 */
export function activateOnKey(handler: () => void) {
  return (e: KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      handler()
    }
  }
}

/**
 * Confidence values arrive on different scales depending on the source
 * (some detectors emit 0–1, some emit 0–100). Normalize to 0–1 so display
 * code can safely multiply by 100. Guards against the "8495%" double-scaling bug.
 */
export function normalizeConfidence(confidence: number): number {
  return confidence > 1 ? confidence / 100 : confidence
}

/** Render a confidence value as a rounded percentage string (e.g. "85%"). */
export function formatConfidencePct(confidence: number): string {
  return `${Math.round(normalizeConfidence(confidence) * 100)}%`
}
