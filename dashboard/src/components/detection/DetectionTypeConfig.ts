import { AlertTriangle, AlertCircle, CheckCircle, RefreshCw, TrendingUp, TrendingDown, Activity, Shield, Zap, Eye, FileWarning, Clock, GitBranch } from 'lucide-react'

export type DetectionType = 'all' | 'loop' | 'state_corruption' | 'persona_drift' | 'coordination' | 'task_derailment' | 'context' | 'communication' | 'specification' | 'decomposition' | 'workflow' | 'hallucination' | 'injection' | 'context_overflow' | 'information_withholding' | 'completion_misjudgment' | 'tool_provision' | 'grounding_failure' | 'retrieval_quality' | 'cost' | 'convergence'

export type Severity = 'all' | 'low' | 'medium' | 'high' | 'critical'

export const detectionTypeConfig: Record<string, { label: string; color: string; icon: typeof AlertTriangle; category: string }> = {
  // Backend-aligned detection type keys
  loop: { label: 'Infinite Loop', color: 'text-red-400', icon: RefreshCw, category: 'Inter-Agent' },
  state_corruption: { label: 'State Corruption', color: 'text-orange-400', icon: AlertTriangle, category: 'System' },
  persona_drift: { label: 'Persona Drift', color: 'text-purple-400', icon: Activity, category: 'Inter-Agent' },
  coordination: { label: 'Coordination Failure', color: 'text-evidence', icon: Zap, category: 'Inter-Agent' },
  task_derailment: { label: 'Task Derailment', color: 'text-pink-400', icon: TrendingUp, category: 'Inter-Agent' },
  context: { label: 'Context Neglect', color: 'text-cyan-400', icon: Eye, category: 'Inter-Agent' },
  communication: { label: 'Communication Breakdown', color: 'text-rose-400', icon: AlertTriangle, category: 'Inter-Agent' },
  specification: { label: 'Spec Mismatch', color: 'text-evidence', icon: Shield, category: 'System' },
  decomposition: { label: 'Poor Decomposition', color: 'text-indigo-400', icon: Activity, category: 'System' },
  workflow: { label: 'Flawed Workflow', color: 'text-violet-400', icon: Zap, category: 'System' },
  hallucination: { label: 'Hallucination', color: 'text-yellow-400', icon: AlertCircle, category: 'System' },
  injection: { label: 'Prompt Injection', color: 'text-red-500', icon: Shield, category: 'System' },
  context_overflow: { label: 'Context Overflow', color: 'text-orange-500', icon: AlertTriangle, category: 'System' },
  information_withholding: { label: 'Info Withholding', color: 'text-teal-400', icon: Eye, category: 'Inter-Agent' },
  completion_misjudgment: { label: 'Completion Issue', color: 'text-lime-400', icon: CheckCircle, category: 'System' },
  tool_provision: { label: 'Tool Provision', color: 'text-evidence', icon: Zap, category: 'System' },
  grounding_failure: { label: 'Grounding Failure', color: 'text-evidence', icon: AlertCircle, category: 'System' },
  retrieval_quality: { label: 'Retrieval Quality', color: 'text-fuchsia-400', icon: Eye, category: 'System' },
  cost: { label: 'Cost Overrun', color: 'text-emerald-400', icon: TrendingUp, category: 'System' },
  convergence: { label: 'Convergence Issue', color: 'text-orange-400', icon: TrendingDown, category: 'System' },
  // Legacy aliases for backwards compatibility with existing DB data
  infinite_loop: { label: 'Infinite Loop', color: 'text-red-400', icon: RefreshCw, category: 'Inter-Agent' },
  overflow: { label: 'Context Overflow', color: 'text-orange-500', icon: AlertTriangle, category: 'System' },
  withholding: { label: 'Info Withholding', color: 'text-teal-400', icon: Eye, category: 'Inter-Agent' },
  completion: { label: 'Completion Issue', color: 'text-lime-400', icon: CheckCircle, category: 'System' },
  coordination_deadlock: { label: 'Coordination Failure', color: 'text-evidence', icon: Zap, category: 'Inter-Agent' },
  context_neglect: { label: 'Context Neglect', color: 'text-cyan-400', icon: Eye, category: 'Inter-Agent' },
  communication_breakdown: { label: 'Communication Breakdown', color: 'text-rose-400', icon: AlertTriangle, category: 'Inter-Agent' },
  specification_mismatch: { label: 'Spec Mismatch', color: 'text-evidence', icon: Shield, category: 'System' },
  poor_decomposition: { label: 'Poor Decomposition', color: 'text-indigo-400', icon: Activity, category: 'System' },
  flawed_workflow: { label: 'Flawed Workflow', color: 'text-violet-400', icon: Zap, category: 'System' },
  convergence_failure: { label: 'Convergence Issue', color: 'text-orange-400', icon: TrendingDown, category: 'System' },
  // pisama-n8n workflow detectors
  cycle: { label: 'Workflow Cycle', color: 'text-red-400', icon: RefreshCw, category: 'Workflow' },
  schema: { label: 'Schema Mismatch', color: 'text-orange-400', icon: FileWarning, category: 'Workflow' },
  resource: { label: 'Resource Explosion', color: 'text-evidence', icon: Zap, category: 'Workflow' },
  timeout: { label: 'Timeout', color: 'text-yellow-400', icon: Clock, category: 'Workflow' },
  error: { label: 'Node Error', color: 'text-red-500', icon: AlertTriangle, category: 'Workflow' },
  complexity: { label: 'Excess Complexity', color: 'text-violet-400', icon: GitBranch, category: 'Workflow' },
  truncation: { label: 'AI Output Truncated', color: 'text-orange-500', icon: FileWarning, category: 'AI workflow' },
  error_workflow: { label: 'Missing Error Workflow', color: 'text-red-500', icon: AlertTriangle, category: 'Workflow' },
  agent_diagnostics: { label: 'Claude Tool or Output Failure', color: 'text-orange-400', icon: Activity, category: 'AI workflow' },
}

export { severityConfig } from '@/lib/severity-config'

// Plain-English labels for n8n users (backend-aligned keys + legacy aliases)
export const plainEnglishLabels: Record<string, string> = {
  loop: 'Stuck in a loop',
  state_corruption: 'Data got corrupted',
  persona_drift: 'Unexpected behavior',
  coordination: 'System stuck',
  task_derailment: 'Got off track',
  context: 'Lost context',
  communication: 'Communication issue',
  specification: 'Wrong output format',
  decomposition: 'Bad task split',
  workflow: 'Workflow problem',
  hallucination: 'Made up facts',
  injection: 'Security threat detected',
  context_overflow: 'Too much data for AI',
  information_withholding: 'Missing information',
  completion_misjudgment: 'Finished too early',
  tool_provision: 'Wrong tools provided',
  grounding_failure: 'Not backed by sources',
  retrieval_quality: 'Wrong documents retrieved',
  cost: 'Over budget',
  convergence: 'Metrics not improving',
  // Legacy aliases
  infinite_loop: 'Stuck in a loop',
  overflow: 'Too much data for AI',
  withholding: 'Missing information',
  completion: 'Finished too early',
  coordination_deadlock: 'System stuck',
  context_neglect: 'Lost context',
  communication_breakdown: 'Communication issue',
  specification_mismatch: 'Wrong output format',
  poor_decomposition: 'Bad task split',
  flawed_workflow: 'Workflow problem',
  convergence_failure: 'Metrics not improving',
  // pisama-n8n workflow detectors
  cycle: 'Workflow loops on itself',
  schema: 'Data shape mismatch',
  resource: 'Runaway resource use',
  timeout: 'Node took too long',
  error: 'A node errored out',
  complexity: 'Workflow too complex',
  truncation: 'AI response was cut short',
  error_workflow: 'No failure alert workflow',
  agent_diagnostics: 'Claude tool recovery or output validation needs attention',
}
