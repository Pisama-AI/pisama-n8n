'use client'

import Link from 'next/link'
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  Check,
  ChevronDown,
  Download,
  FlaskConical,
  History,
  Play,
  ShieldCheck,
} from 'lucide-react'
import { Layout } from '@/components/common/Layout'
import { Button, buttonVariants } from '@/components/ui/Button'
import { Card, CardHeader, CardTitle, EmptyState } from '@/components/ui'
import { Skeleton } from '@/components/ui/Skeleton'
import {
  createEvaluationRun,
  exportEvaluationCases,
  getEvaluationCaseRevisions,
  getEvaluationCases,
  getEvaluationRuns,
  reviseEvaluationCase,
  submitDetectionFeedback,
  type EvaluationCase,
  type EvaluationRunCase,
  type EvaluationSplit,
} from '@/lib/api/detections'

const LOOP_STEPS = ['Captured', 'Reviewed', 'Frozen', 'Scored']

function percentage(value: number | null | undefined): string {
  return value == null ? 'Pending' : `${Math.round(value * 100)}%`
}

function displayRevision(revision: string): string {
  return /^[0-9a-f]{40}$/i.test(revision) ? revision.slice(0, 12) : revision
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <Card padding="lg">
      <div className="font-mono text-2xl text-ink">{value}</div>
      <div className="mt-1 text-xs text-ink-3">{label}</div>
    </Card>
  )
}

function LoopStatus({ hasCases, hasScore }: { hasCases: boolean; hasScore: boolean }) {
  return (
    <Card padding="lg" aria-label="Closed-loop status">
      <ol className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {LOOP_STEPS.map((step, index) => {
          const complete = index < 3 ? hasCases : hasScore
          return (
            <li key={step} className="flex items-center gap-3">
              <span
                className={`flex h-7 w-7 items-center justify-center rounded-full border text-xs font-medium ${
                  complete
                    ? 'border-evidence bg-evidence/10 text-evidence'
                    : 'border-rule text-ink-4'
                }`}
              >
                {complete ? <Check size={14} aria-hidden="true" /> : index + 1}
              </span>
              <span className={complete ? 'text-sm text-ink-2' : 'text-sm text-ink-4'}>{step}</span>
            </li>
          )
        })}
      </ol>
    </Card>
  )
}

function RevisionPanel({ item }: { item: EvaluationCase }) {
  const queryClient = useQueryClient()
  const [modes, setModes] = useState(item.expected_modes.join(', '))
  const [split, setSplit] = useState<EvaluationSplit>(item.split)
  const [evidence, setEvidence] = useState('')
  const revisions = useQuery({
    queryKey: ['evaluation-case-revisions', item.id],
    queryFn: () => getEvaluationCaseRevisions(item.id),
  })
  const correction = useMutation({
    mutationFn: async () => {
      const expectedModes = [...new Set(modes.split(',').map((mode) => mode.trim()).filter(Boolean))]
      await submitDetectionFeedback(String(item.detection_id), 'useful')
      return reviseEvaluationCase(item.id, expectedModes, split, evidence)
    },
    onSuccess: async () => {
      setEvidence('')
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['evaluation-cases'] }),
        queryClient.invalidateQueries({ queryKey: ['evaluation-case-revisions', item.id] }),
      ])
    },
  })

  return (
    <div className="border-t border-rule bg-surface-2 px-5 py-5">
      <div className="grid gap-6 lg:grid-cols-2">
        <div>
          <div className="mb-3 flex items-center gap-2 text-xs font-medium text-ink-2">
            <History size={14} /> Append-only revision history
          </div>
          <ol className="space-y-3">
            {(revisions.data ?? []).map((revision) => (
              <li key={revision.revision} className="border-l border-rule pl-3 text-xs text-ink-3">
                <div className="font-medium text-ink-2">
                  Revision {revision.revision} · {revision.split}
                </div>
                <div className="mt-1 font-mono">
                  {revision.expected_modes.join(', ') || 'No failure modes expected'}
                </div>
                <p className="mt-1 leading-relaxed">{revision.label_evidence}</p>
                <div className="mt-1 text-ink-4">{revision.created_by_principal}</div>
              </li>
            ))}
          </ol>
        </div>
        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault()
            correction.mutate()
          }}
        >
          <div className="text-xs font-medium text-ink-2">Record a reviewed correction</div>
          <label className="block text-xs text-ink-3">
            Expected modes, comma separated
            <input
              className="mt-1 w-full rounded-md border border-rule bg-surface px-3 py-2 font-mono text-xs text-ink outline-none focus:border-ink-3"
              value={modes}
              onChange={(event) => setModes(event.target.value)}
            />
          </label>
          <label className="block text-xs text-ink-3">
            Split
            <select
              className="mt-1 w-full rounded-md border border-rule bg-surface px-3 py-2 text-xs text-ink outline-none focus:border-ink-3"
              value={split}
              onChange={(event) => setSplit(event.target.value as EvaluationSplit)}
            >
              <option value="regression">Regression</option>
              <option value="holdout">Holdout</option>
            </select>
          </label>
          <label className="block text-xs text-ink-3">
            Evidence for this correction
            <textarea
              required
              className="mt-1 min-h-20 w-full rounded-md border border-rule bg-surface px-3 py-2 text-xs text-ink outline-none focus:border-ink-3"
              value={evidence}
              onChange={(event) => setEvidence(event.target.value)}
            />
          </label>
          {correction.isError ? (
            <p className="text-xs text-red-500">
              The correction was not saved. Verify the modes and try again.
            </p>
          ) : null}
          <Button type="submit" size="sm" isLoading={correction.isPending} disabled={!evidence.trim()}>
            Append correction
          </Button>
        </form>
      </div>
    </div>
  )
}

function CaseRow({ item, result }: { item: EvaluationCase; result?: EvaluationRunCase }) {
  const [expanded, setExpanded] = useState(false)
  return (
    <div>
      <div className="grid gap-4 px-5 py-5 md:grid-cols-[1fr_1.4fr_auto] md:items-center">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-ink">
              {item.corpus_case_id ?? `Case ${item.id}`}
            </span>
            <span className="rounded border border-rule px-2 py-0.5 text-[10px] uppercase tracking-wide text-ink-3">
              {item.split}
            </span>
            <span className="text-xs text-ink-4">revision {item.revision}</span>
          </div>
          <div className="mt-2 font-mono text-[11px] text-ink-4" title={item.payload_sha256 ?? undefined}>
            sha256 {item.payload_sha256?.slice(0, 12) ?? 'unavailable'}
          </div>
        </div>
        <div>
          <div className="font-mono text-xs text-ink-2">
            {item.expected_modes.join(', ') || 'No failure modes expected'}
          </div>
          <p className="mt-2 text-xs leading-relaxed text-ink-3">{item.label_evidence}</p>
          {result && result.exact_match === false ? (
            <p className="mt-2 text-xs text-red-500">
              Missing: {result.missing_modes.join(', ') || 'none'}. Unexpected:{' '}
              {result.unexpected_modes.join(', ') || 'none'}.
            </p>
          ) : null}
        </div>
        <div className="flex items-center gap-3 text-xs">
          {result?.exact_match === true ? (
            <span className="flex items-center gap-1">
              <ShieldCheck size={15} className="text-evidence" /> Exact match
            </span>
          ) : result?.exact_match === false ? (
            <span className="flex items-center gap-1">
              <AlertTriangle size={15} className="text-red-500" /> Mismatch
            </span>
          ) : (
            <span className="text-ink-4">Not scored</span>
          )}
          <button
            type="button"
            className="flex items-center gap-1 text-ink-3 hover:text-ink"
            aria-expanded={expanded}
            onClick={() => setExpanded((value) => !value)}
          >
            Review <ChevronDown size={13} className={expanded ? 'rotate-180' : ''} />
          </button>
        </div>
      </div>
      {expanded ? <RevisionPanel item={item} /> : null}
    </div>
  )
}

export function EvaluationClient() {
  const queryClient = useQueryClient()
  const [downloading, setDownloading] = useState(false)
  const [downloadError, setDownloadError] = useState(false)
  const casesQuery = useQuery({ queryKey: ['evaluation-cases'], queryFn: getEvaluationCases })
  const runsQuery = useQuery({
    queryKey: ['evaluation-runs'],
    queryFn: getEvaluationRuns,
    refetchInterval: (query) =>
      query.state.data?.some((run) => run.status === 'pending' || run.status === 'running')
        ? 500
        : false,
  })
  const runMutation = useMutation({
    mutationFn: createEvaluationRun,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['evaluation-runs'] }),
  })
  const cases = casesQuery.data ?? []
  const runs = runsQuery.data ?? []
  const latestRun = runs[0]
  const scoredRun = runs.find((run) => run.status === 'succeeded')
  const score = scoredRun?.result
  const scoreByCaseId = useMemo(
    () => new Map(scoredRun?.cases.map((result) => [result.evaluation_case_id, result]) ?? []),
    [scoredRun]
  )

  async function download() {
    setDownloading(true)
    setDownloadError(false)
    try {
      const manifest = await exportEvaluationCases()
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(manifest, null, 2)], { type: 'application/json' })
      )
      const link = document.createElement('a')
      link.href = url
      link.download = `pisama-evaluation-taxonomy-v${manifest.taxonomy_version}.json`
      link.click()
      URL.revokeObjectURL(url)
    } catch {
      setDownloadError(true)
    } finally {
      setDownloading(false)
    }
  }

  return (
    <Layout title="Evaluation">
      <div className="mx-auto max-w-5xl space-y-6">
        <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
          <div>
            <h2 className="font-serif text-2xl text-ink">Closed-loop evaluation</h2>
            <p className="mt-1 max-w-2xl text-sm leading-relaxed text-ink-3">
              Immutable score runs over independently reviewed n8n executions.
            </p>
          </div>
          {cases.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              <Button variant="secondary" leftIcon={<Download size={14} />} isLoading={downloading} onClick={download}>
                Download corpus
              </Button>
              <Button leftIcon={<Play size={14} />} isLoading={runMutation.isPending || latestRun?.status === 'running'} onClick={() => runMutation.mutate()}>
                Run regression suite
              </Button>
            </div>
          ) : null}
        </div>

        <LoopStatus hasCases={cases.length > 0} hasScore={Boolean(scoredRun)} />

        {casesQuery.isLoading || runsQuery.isLoading ? (
          <div className="grid gap-4 sm:grid-cols-4">
            {Array.from({ length: 4 }, (_, index) => <Skeleton key={index} className="h-24" />)}
          </div>
        ) : casesQuery.isError || runsQuery.isError ? (
          <Card><EmptyState icon={AlertTriangle} title="Could not load evaluation evidence" description="Check the server connection and dashboard credentials, then try again." /></Card>
        ) : cases.length === 0 ? (
          <Card>
            <EmptyState
              icon={FlaskConical}
              title="No reviewed evaluation cases yet"
              description="Open a fired detection, record a verdict, verify the labels against n8n evidence, and freeze the execution."
              action={<Link href="/detections" className={buttonVariants({ variant: 'primary', size: 'md' })}>Review detections</Link>}
            />
          </Card>
        ) : (
          <>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Metric label="Reviewed corpus" value={cases.length} />
              <Metric label="Audited run cases" value={scoredRun?.case_count ?? 'Pending'} />
              <Metric label="Exact set accuracy" value={percentage(score?.exact_set_accuracy)} />
              <Metric label="Holdout cases" value={cases.filter((item) => item.split === 'holdout').length} />
            </div>

            {latestRun ? (
              <Card padding="lg">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-medium text-ink">Immutable run {latestRun.id}</div>
                    <div className="mt-1 text-xs text-ink-3">
                      {latestRun.case_count} cases · taxonomy v{latestRun.taxonomy_version} · build {displayRevision(latestRun.build_revision)}
                    </div>
                  </div>
                  <span className="rounded border border-rule px-2.5 py-1 text-xs uppercase tracking-wide text-ink-2">
                    {latestRun.status}
                  </span>
                </div>
                {latestRun.error ? <p className="mt-3 text-xs text-red-500">{latestRun.error}</p> : null}
              </Card>
            ) : null}

            {runMutation.isError ? (
              <Card padding="lg" className="border-red-500/30">
                <div className="flex items-center gap-2 text-sm text-red-500">
                  <AlertTriangle size={16} /> The regression run could not be queued.
                </div>
              </Card>
            ) : null}
            {downloadError ? <p className="text-sm text-red-500">The reviewed corpus could not be downloaded.</p> : null}

            <Card padding="none">
              <CardHeader className="mb-0 border-b border-rule px-5 py-4">
                <CardTitle>Reviewed corpus</CardTitle>
                <p className="mt-1 text-xs text-ink-3">
                  {cases.length} provenance-backed cases. Expand a row to inspect or append a label correction.
                </p>
              </CardHeader>
              <div className="divide-y divide-rule">
                {cases.map((item) => <CaseRow key={item.id} item={item} result={scoreByCaseId.get(item.id)} />)}
              </div>
            </Card>

            <p className="border-l-2 border-evidence pl-4 text-xs leading-relaxed text-ink-3">
              Regression runs exclude holdout cases. A holdout enters a run only through a sealed,
              owner-controlled protocol that freezes its revision, label hash, and payload hash.
            </p>
          </>
        )}
      </div>
    </Layout>
  )
}
