'use client'

import { useState, useRef } from 'react'
import { cn } from '@/lib/utils'

export interface TooltipProps {
  content: React.ReactNode
  children: React.ReactNode
  position?: 'top' | 'bottom' | 'left' | 'right'
  className?: string
}

export function Tooltip({ content, children, position = 'top', className }: TooltipProps) {
  const [isVisible, setIsVisible] = useState(false)
  const tooltipRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLSpanElement>(null)

  const positionClasses = {
    top: 'bottom-full left-1/2 -translate-x-1/2 mb-2',
    bottom: 'top-full left-1/2 -translate-x-1/2 mt-2',
    left: 'right-full top-1/2 -translate-y-1/2 mr-2',
    right: 'left-full top-1/2 -translate-y-1/2 ml-2',
  }

  const arrowClasses = {
    top: 'top-full left-1/2 -translate-x-1/2 border-t-zinc-800 border-x-transparent border-b-transparent',
    bottom: 'bottom-full left-1/2 -translate-x-1/2 border-b-zinc-800 border-x-transparent border-t-transparent',
    left: 'left-full top-1/2 -translate-y-1/2 border-l-zinc-800 border-y-transparent border-r-transparent',
    right: 'right-full top-1/2 -translate-y-1/2 border-r-zinc-800 border-y-transparent border-l-transparent',
  }

  return (
    <span
      ref={triggerRef}
      className="relative inline-flex"
      onMouseEnter={() => setIsVisible(true)}
      onMouseLeave={() => setIsVisible(false)}
      onFocus={() => setIsVisible(true)}
      onBlur={() => setIsVisible(false)}
    >
      {children}
      {isVisible && (
        <div
          ref={tooltipRef}
          role="tooltip"
          className={cn(
            'absolute z-50 px-3 py-2 text-sm text-ink bg-paper-2 border border-rule rounded-md shadow-elevated whitespace-normal max-w-xs',
            positionClasses[position],
            className
          )}
        >
          {content}
          <span
            className={cn(
              'absolute w-0 h-0 border-4',
              arrowClasses[position]
            )}
          />
        </div>
      )}
    </span>
  )
}

// Terminology definitions for non-technical users
const terminology: Record<string, { term: string; definition: string; example?: string }> = {
  trace: {
    term: 'Workflow Run',
    definition: 'A complete record of your workflow running from start to finish, like a detailed log of what happened.',
    example: 'When a customer submits a form and your workflow processes it, that\'s one workflow run.'
  },
  span: {
    term: 'Step',
    definition: 'A single action in your workflow, like sending an email or calling an API.',
  },
  detection: {
    term: 'Problem Found',
    definition: 'We automatically identified something that might be causing issues with your workflow.',
  },
  infinite_loop: {
    term: 'Workflow Running Forever',
    definition: 'Your workflow is repeating the same steps over and over without stopping, which wastes resources and could cause errors.',
    example: 'Like a record player stuck in a groove, playing the same part repeatedly.'
  },
  state_corruption: {
    term: 'Data Got Scrambled',
    definition: 'Information being passed between steps got mixed up or lost, causing incorrect results.',
  },
  persona_drift: {
    term: 'AI Changed Personality',
    definition: 'The AI assistant in your workflow started behaving differently than expected, giving inconsistent responses.',
  },
  coordination_deadlock: {
    term: 'Steps Waiting Forever',
    definition: 'Multiple steps in your workflow are waiting for each other, so nothing can proceed. Like two people both waiting for the other to go first.',
  },
  staged: {
    term: 'Ready to Test',
    definition: 'The fix has been prepared but is turned off so you can test it safely before making it live.',
  },
  rollback: {
    term: 'Undo the Fix',
    definition: 'Restore your workflow to how it was before the fix was applied, if something went wrong.',
  },
  confidence: {
    term: 'How Certain We Are',
    // Deliberately NOT a probability: detectors emit a small set of fixed certainty
    // levels, so any percentage here would imply a calibrated likelihood we do not
    // measure. Describe the tier in evidence terms instead.
    definition:
      'How strong the evidence is for this finding — High, Likely, Possible, or Low. It reflects how much supporting signal the detector found, not a measured probability.',
  },
  diff: {
    term: 'Before/After Comparison',
    definition: 'Shows what will change in your workflow - highlighted lines show what\'s being added or removed.',
  },
}

export interface TermTooltipProps {
  term: keyof typeof terminology | string
  children?: React.ReactNode
  showIcon?: boolean
}

export function TermTooltip({ term, children, showIcon = true }: TermTooltipProps) {
  const info = terminology[term.toLowerCase().replace(/ /g, '_')]

  if (!info) {
    return <span>{children || term}</span>
  }

  return (
    <Tooltip
      content={
        <div className="space-y-1">
          <p className="font-medium text-ink">{info.term}</p>
          <p className="text-ink-3">{info.definition}</p>
          {info.example && (
            <p className="text-ink-3 text-xs italic">Example: {info.example}</p>
          )}
        </div>
      }
      position="top"
    >
      <span
        tabIndex={0}
        role="button"
        aria-label={typeof info.term === 'string' ? `Definition: ${info.term}` : 'Show definition'}
        className="inline-flex items-center gap-1 border-b border-dashed border-rule cursor-help focus:outline-none focus:ring-2 focus:ring-evidence focus:ring-offset-1 focus:ring-offset-zinc-900 rounded-sm"
      >
        {children || info.term}
        {showIcon && (
          <svg className="w-3 h-3 text-ink-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        )}
      </span>
    </Tooltip>
  )
}

// Helper to translate detection types to plain English
export function getPlainEnglishTitle(detectionType: string): string {
  const translations: Record<string, string> = {
    'infinite_loop': 'Workflow Running Forever',
    'state_corruption': 'Data Got Scrambled',
    'persona_drift': 'AI Changed Personality',
    'coordination_deadlock': 'Steps Waiting for Each Other',
    'tool_misuse': 'Tool Used Incorrectly',
    'hallucination': 'AI Made Something Up',
    'context_overflow': 'Too Much Information',
    'latency_degradation': 'Workflow Getting Slower',
    'cost_anomaly': 'Unexpected Costs',
  }

  return translations[detectionType.toLowerCase()] || detectionType.replace(/_/g, ' ')
}

// Helper to translate status to plain English
export function getPlainEnglishStatus(status: string): { label: string; description: string } {
  const translations: Record<string, { label: string; description: string }> = {
    'pending': { label: 'Waiting', description: 'Fix is being prepared' },
    'in_progress': { label: 'Working on it', description: 'Fix is being applied' },
    'staged': { label: 'Ready to test', description: 'Fix is ready but not live yet - test it first' },
    'applied': { label: 'Fixed!', description: 'Fix has been applied and is working' },
    'failed': { label: 'Couldn\'t fix', description: 'Something went wrong applying the fix' },
    'rolled_back': { label: 'Undone', description: 'Fix was removed and workflow restored' },
    'rejected': { label: 'Not applied', description: 'Fix was reviewed and decided against' },
    'promoted': { label: 'Live', description: 'Fix has been tested and is now active' },
  }

  return translations[status.toLowerCase()] || { label: status, description: '' }
}
