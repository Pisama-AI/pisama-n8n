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

// NOTE: confidence-as-percentage helpers were removed deliberately. Detector
// confidence is a small lattice of fixed levels (0.95/0.90/0.85/…), not a measured
// likelihood, so rendering "95%" implied a calibrated probability that is not measured.
// Confidence is surfaced as a TIER instead — see confidenceTier() in the detection
// detail view and severityFromConfidence() in lib/api/detections.ts. If a genuine
// probability is ever needed, it has to come from a fitted calibration, not from
// formatting the raw constant.
