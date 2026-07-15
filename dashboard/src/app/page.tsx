import type { Metadata } from 'next'
import Link from 'next/link'
import {
  RefreshCw,
  Clock,
  AlertTriangle,
  Zap,
  GitBranch,
  FileWarning,
  Webhook,
  RadioTower,
  TerminalSquare,
  Sparkles,
} from 'lucide-react'
import { PisamaMark } from '@/components/common/PisamaMark'

export const metadata: Metadata = {
  title: 'Pisama for n8n: failure detection for your workflows',
  description:
    'Detect failures in n8n workflow executions: timeouts, node errors, runaway loops, resource explosions. Fair-code, self-hostable, with a paid cloud tier for AI fix suggestions and auto-apply.',
}

const DETECTORS = [
  {
    icon: Clock,
    name: 'Timeout',
    desc: 'A node genuinely ran past its threshold in a real execution, likely timing out the caller.',
  },
  {
    icon: AlertTriangle,
    name: 'Node error',
    desc: 'A node threw during the run, including failures hidden by continue-on-fail settings.',
  },
  {
    icon: Zap,
    name: 'Resource explosion',
    desc: 'Output payloads or item counts ballooned mid-run, the pattern behind memory and quota blowups.',
  },
  {
    icon: RefreshCw,
    name: 'Unbounded cycle',
    desc: 'A workflow graph cycle with no exit and no iteration bound. Intentional batch loops are recognized and left alone.',
  },
  {
    icon: GitBranch,
    name: 'Excess complexity',
    desc: 'Control flow tangled enough to be a reliability risk, calibrated on thousands of real community workflows.',
  },
  {
    icon: FileWarning,
    name: 'Schema drift',
    desc: 'Runtime output shape changes between executions. Static guessing is deliberately disabled; only real signal fires.',
  },
]

const CHANNELS = [
  {
    icon: Webhook,
    name: 'Community node or webhook',
    desc: 'Install the n8n-nodes-pisama node, or point any HTTP node or error workflow at the ingest endpoint.',
  },
  {
    icon: RadioTower,
    name: 'API polling, zero setup',
    desc: 'Give the server your n8n API key and it polls recent executions on its own. No workflow edits at all.',
  },
  {
    icon: TerminalSquare,
    name: 'Self-host in one command',
    desc: 'docker compose up starts the detection server and this dashboard on your own machine.',
  },
]

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="font-mono text-xs uppercase tracking-[0.18em] text-evidence mb-4">
      {children}
    </div>
  )
}

export default function Landing() {
  return (
    <main className="min-h-screen bg-paper text-ink">
      {/* nav */}
      <header className="border-b border-rule">
        <div className="mx-auto max-w-5xl px-6 py-5 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <PisamaMark size={26} color="var(--ink)" />
            <span className="font-serif text-lg">
              pisama <span className="text-ink-3">for n8n</span>
            </span>
          </div>
          <nav className="flex items-center gap-5 text-sm">
            <a
              href="https://github.com/Pisama-AI/pisama-n8n"
              className="text-ink-3 hover:text-ink transition-colors"
            >
              GitHub
            </a>
            <Link
              href="/overview"
              className="px-4 py-2 rounded-lg bg-evidence text-evidence-ink font-medium hover:bg-evidence-2 transition-colors"
            >
              Open dashboard
            </Link>
          </nav>
        </div>
      </header>

      {/* hero */}
      <section className="mx-auto max-w-5xl px-6 pt-20 pb-16">
        <h1 className="font-serif text-4xl md:text-5xl leading-tight max-w-3xl">
          Your n8n workflows fail quietly.
          <br />
          <span className="text-evidence">This catches them.</span>
        </h1>
        <p className="mt-6 max-w-2xl text-lg text-ink-2 leading-relaxed">
          Pisama for n8n watches real workflow executions and detects the failures that
          slip through: nodes that time out, errors swallowed by continue-on-fail, loops
          that never end, payloads that explode. Fair-code and self-hostable. Your
          execution data stays on your machine.
        </p>
        <div className="mt-8 flex flex-wrap items-center gap-4">
          <Link
            href="/overview"
            className="px-5 py-2.5 rounded-lg bg-evidence text-evidence-ink font-semibold hover:bg-evidence-2 transition-colors"
          >
            See it running
          </Link>
          <a
            href="https://github.com/Pisama-AI/pisama-n8n"
            className="px-5 py-2.5 rounded-lg border border-rule text-ink-2 hover:text-ink hover:border-ink-4 transition-colors"
          >
            Read the source
          </a>
        </div>
        <div className="mt-10 rounded-lg border border-rule bg-paper-2 p-4 font-mono text-sm text-ink-2 overflow-x-auto">
          <span className="text-ink-4">$</span> git clone
          https://github.com/Pisama-AI/pisama-n8n && cd pisama-n8n/deploy && docker
          compose up
        </div>
      </section>

      {/* detectors */}
      <section className="border-t border-rule bg-paper-2/40">
        <div className="mx-auto max-w-5xl px-6 py-16">
          <SectionLabel>Six detectors, two lanes</SectionLabel>
          <h2 className="font-serif text-2xl mb-3">
            Structural analysis of the workflow, runtime analysis of the execution
          </h2>
          <p className="text-ink-3 max-w-2xl mb-10">
            The structural lane reads the workflow graph itself. The runtime lane reads
            what actually happened in an execution: real timings, real errors, real
            payload sizes. Precision is tuned against thousands of real community
            workflows.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {DETECTORS.map((d) => (
              <div key={d.name} className="rounded-lg border border-rule bg-paper-2 p-5">
                <d.icon size={18} className="text-evidence mb-3" />
                <div className="font-semibold text-sm mb-1.5">{d.name}</div>
                <p className="text-sm text-ink-3 leading-relaxed">{d.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* channels */}
      <section className="border-t border-rule">
        <div className="mx-auto max-w-5xl px-6 py-16">
          <SectionLabel>Three ways in</SectionLabel>
          <h2 className="font-serif text-2xl mb-10">
            Works with n8n Cloud and self-hosted, no workflow rewrites
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {CHANNELS.map((c) => (
              <div key={c.name} className="rounded-lg border border-rule bg-paper-2 p-5">
                <c.icon size={18} className="text-evidence mb-3" />
                <div className="font-semibold text-sm mb-1.5">{c.name}</div>
                <p className="text-sm text-ink-3 leading-relaxed">{c.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* paid tier */}
      <section className="border-t border-rule bg-paper-2/40">
        <div className="mx-auto max-w-5xl px-6 py-16">
          <div className="rounded-lg border border-rule bg-paper-2 p-8 md:flex items-center justify-between gap-8">
            <div className="max-w-xl">
              <div className="flex items-center gap-2 mb-3">
                <Sparkles size={16} className="text-evidence" />
                <span className="font-mono text-xs uppercase tracking-[0.18em] text-evidence">
                  Paid cloud tier
                </span>
              </div>
              <h2 className="font-serif text-2xl mb-3">
                From detection to a fix you can apply
              </h2>
              <p className="text-ink-3 leading-relaxed">
                The cloud tier generates a targeted fix for each detection, previews the
                exact change, and applies it to your live workflow with one approval.
                Every apply is snapshotted and reversible. Your n8n credentials never
                leave your network; the cloud sees only the traces you send it.
              </p>
            </div>
            <div className="mt-6 md:mt-0 shrink-0">
              <a
                href="https://pisama.ai"
                className="inline-block px-5 py-2.5 rounded-lg border border-evidence text-evidence font-medium hover:bg-evidence hover:text-evidence-ink transition-colors"
              >
                Learn about Pisama Cloud
              </a>
            </div>
          </div>
        </div>
      </section>

      {/* footer */}
      <footer className="border-t border-rule">
        <div className="mx-auto max-w-5xl px-6 py-10 flex flex-col md:flex-row items-start md:items-center justify-between gap-4 text-sm text-ink-4">
          <div className="flex items-center gap-2.5">
            <PisamaMark size={18} color="var(--ink-4)" />
            <span>Pisama for n8n. Fair-code, source-available.</span>
          </div>
          <div className="flex items-center gap-5">
            <a
              href="https://github.com/Pisama-AI/pisama-n8n"
              className="hover:text-ink-2 transition-colors"
            >
              GitHub
            </a>
            <a
              href="https://www.npmjs.com/package/n8n-nodes-pisama"
              className="hover:text-ink-2 transition-colors"
            >
              n8n node
            </a>
            <a href="https://pisama.ai" className="hover:text-ink-2 transition-colors">
              pisama.ai
            </a>
          </div>
        </div>
      </footer>
    </main>
  )
}
