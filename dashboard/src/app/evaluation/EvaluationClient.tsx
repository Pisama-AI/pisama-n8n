'use client'

import Link from 'next/link'
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Check, Download, FlaskConical, Play, ShieldCheck } from 'lucide-react'
import { Layout } from '@/components/common/Layout'
import { Button, buttonVariants } from '@/components/ui/Button'
import { Card, CardHeader, CardTitle, EmptyState } from '@/components/ui'
import { Skeleton } from '@/components/ui/Skeleton'
import {
  exportEvaluationCases,
  getEvaluationCases,
  scoreEvaluationCases,
  type EvaluationCase,
  type EvaluationScore,
  type EvaluationScoreCase,
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

function CaseRow({ item, result }: { item: EvaluationCase; result?: EvaluationScoreCase }) {
  return (
    <div className="grid gap-4 px-5 py-5 md:grid-cols-[1fr_1.4fr_auto] md:items-center">
      <div>
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-ink">Case {item.id}</span>
          <span className="rounded border border-rule px-2 py-0.5 text-[10px] uppercase tracking-wide text-ink-3">
            {item.split}
          </span>
          <span className="text-xs text-ink-4">revision {item.revision}</span>
        </div>
        <div
          className="mt-2 font-mono text-[11px] text-ink-4"
          title={item.payload_sha256 ?? undefined}
        >
          sha256 {item.payload_sha256?.slice(0, 12) ?? 'unavailable'}
        </div>
      </div>
      <div>
        <div className="font-mono text-xs text-ink-2">
          {item.expected_modes.join(', ') || 'No failure modes expected'}
        </div>
        <p className="mt-2 text-xs leading-relaxed text-ink-3">{item.label_evidence}</p>
        {result && !result.exact_match ? (
          <p className="mt-2 text-xs text-red-500">
            Missing: {result.missing_modes.join(', ') || 'none'}. Unexpected:{' '}
            {result.unexpected_modes.join(', ') || 'none'}.
          </p>
        ) : null}
      </div>
      <div className="flex items-center gap-2 text-xs">
        {result ? (
          result.exact_match ? (
            <>
              <ShieldCheck size={15} className="text-evidence" /> Exact match
            </>
          ) : (
            <>
              <AlertTriangle size={15} className="text-red-500" /> Mismatch
            </>
          )
        ) : (
          <span className="text-ink-4">Not scored</span>
        )}
      </div>
    </div>
  )
}

export function EvaluationClient() {
  const [downloading, setDownloading] = useState(false)
  const [downloadError, setDownloadError] = useState(false)
  const casesQuery = useQuery({
    queryKey: ['evaluation-cases'],
    queryFn: getEvaluationCases,
  })
  const cases = casesQuery.data ?? []
  const scoreQuery = useQuery({
    queryKey: ['evaluation-score'],
    queryFn: scoreEvaluationCases,
    enabled: cases.length > 0,
  })
  const score = scoreQuery.data
  const scoreByCaseId = useMemo(
    () => new Map(score?.cases.map((result) => [result.id, result]) ?? []),
    [score]
  )

  async function download() {
    setDownloading(true)
    setDownloadError(false)
    try {
      const manifest = await exportEvaluationCases()
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(manifest, null, 2)], {
          type: 'application/json',
        })
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
              Score independently reviewed n8n executions against the detector build running now.
            </p>
          </div>
          {cases.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              <Button
                variant="secondary"
                leftIcon={<Download size={14} />}
                isLoading={downloading}
                onClick={download}
              >
                Download corpus
              </Button>
              <Button
                leftIcon={<Play size={14} />}
                isLoading={scoreQuery.isFetching}
                onClick={() => scoreQuery.refetch()}
              >
                Run evaluation suite
              </Button>
            </div>
          ) : null}
        </div>

        <LoopStatus hasCases={cases.length > 0} hasScore={Boolean(score)} />

        {casesQuery.isLoading ? (
          <div className="grid gap-4 sm:grid-cols-4">
            {Array.from({ length: 4 }, (_, index) => (
              <Skeleton key={index} className="h-24" />
            ))}
          </div>
        ) : casesQuery.isError ? (
          <Card>
            <EmptyState
              icon={AlertTriangle}
              title="Could not load the reviewed corpus"
              description="Check the server connection and dashboard credentials, then try again."
            />
          </Card>
        ) : cases.length === 0 ? (
          <Card>
            <EmptyState
              icon={FlaskConical}
              title="No reviewed evaluation cases yet"
              description="Open a fired detection, record a verdict, verify the labels against n8n evidence, and freeze the execution."
              action={
                <Link
                  href="/detections"
                  className={buttonVariants({ variant: 'primary', size: 'md' })}
                >
                  Review detections
                </Link>
              }
            />
          </Card>
        ) : (
          <>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Metric label="Reviewed cases" value={cases.length} />
              <Metric label="Exact set accuracy" value={percentage(score?.exact_set_accuracy)} />
              <Metric
                label="Regression cases"
                value={
                  score?.by_split.regression.n ??
                  cases.filter((item) => item.split === 'regression').length
                }
              />
              <Metric
                label="Holdout cases"
                value={
                  score?.by_split.holdout.n ??
                  cases.filter((item) => item.split === 'holdout').length
                }
              />
            </div>

            {scoreQuery.isError ? (
              <Card padding="lg" className="border-red-500/30">
                <div className="flex items-center gap-2 text-sm text-red-500">
                  <AlertTriangle size={16} /> The current corpus could not be scored.
                </div>
              </Card>
            ) : null}

            {downloadError ? (
              <p className="text-sm text-red-500">
                The reviewed corpus could not be downloaded. Check the server connection and retry.
              </p>
            ) : null}

            <Card padding="none">
              <CardHeader className="mb-0 border-b border-rule px-5 py-4">
                <CardTitle>Reviewed corpus</CardTitle>
                <p className="mt-1 text-xs text-ink-3">
                  Taxonomy v{score?.taxonomy_version ?? cases[0].taxonomy_version}
                  {score ? ` · build ${displayRevision(score.build_revision)}` : ''}
                </p>
              </CardHeader>
              <div className="divide-y divide-rule">
                {cases.map((item) => (
                  <CaseRow
                    key={item.id}
                    item={item}
                    result={scoreByCaseId.get(`tenant-evaluation-${item.id}`)}
                  />
                ))}
              </div>
            </Card>

            <p className="border-l-2 border-evidence pl-4 text-xs leading-relaxed text-ink-3">
              Exact matches on reviewed retained cases are regression evidence for this detector
              build. They do not estimate accuracy across unreviewed production traffic. Keep
              holdout labels separate and disclose their count when reporting results.
            </p>
          </>
        )}
      </div>
    </Layout>
  )
}
