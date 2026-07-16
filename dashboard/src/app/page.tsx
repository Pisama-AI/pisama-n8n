import type { Metadata } from 'next'
import Link from 'next/link'
import {
  RefreshCw,
  Clock,
  AlertTriangle,
  Zap,
  GitBranch,
  Webhook,
  RadioTower,
  TerminalSquare,
  Sparkles,
  Check,
} from 'lucide-react'
import { PisamaMark } from '@/components/common/PisamaMark'

export const metadata: Metadata = {
  title: 'Pisama for n8n: failure detection for your workflows',
  description:
    'Detect failures in n8n workflow executions. Self-host the fair-code version, or use the free and Pro cloud plans for AI fixes and approvals.',
}

const DETECTORS = [
  {
    icon: Clock,
    name: 'Timeout',
    desc: 'A node genuinely ran past its threshold in a real execution, likely timing out the caller.',
  },
  {
    icon: AlertTriangle,
    name: 'Classified failure',
    desc: 'A real node error is classified as rate-limit, credential, provider, expression, timeout, or node failure.',
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
    icon: AlertTriangle,
    name: 'Recovery safeguards',
    desc: 'Observed retries, missing error workflows, and repeated unsafe HTTP actions are surfaced only when execution evidence supports them.',
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

const PLAN_FEATURES = [
  ['Deployment', 'Self-hosted', 'Pisama cloud', 'Pisama cloud'],
  ['n8n connections', 'You manage them', '1', '5'],
  ['Failure detection', 'Evidence-gated detectors', 'Evidence-gated detectors', 'Evidence-gated detectors'],
  ['AI fix suggestions', 'With a cloud key', 'Not included', 'Monthly allocation'],
  ['Apply approved fixes', 'With a cloud key', 'Not included', 'Snapshots and rollback'],
]

const FIRST_DETECTION_STEPS = [
  {
    title: 'Connect your n8n',
    desc: 'Use the community node, a webhook, or a read-only n8n API key.',
  },
  {
    title: 'Read real executions',
    desc: 'Pisama checks timings, errors, payload size, and workflow structure.',
  },
  {
    title: 'Review what needs action',
    desc: 'Open the evidence behind each detection and decide the next step.',
  },
]

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="font-mono text-xs uppercase tracking-[0.18em] text-evidence mb-4">
      {children}
    </div>
  )
}

function PlanComparison() {
  return (
    <section id="plans" className="border-t border-rule bg-paper-2/40 scroll-mt-6">
      <div className="mx-auto max-w-5xl px-6 py-16">
        <SectionLabel>Choose your setup</SectionLabel>
        <div className="md:flex items-end justify-between gap-8 mb-10">
          <div className="max-w-2xl">
            <h2 className="font-serif text-2xl mb-3">Start where the workflow lives</h2>
            <p className="text-ink-3 leading-relaxed">
              Run Pisama yourself, start with hosted detection at no cost, or give your
              team AI-assisted fixes when a detection needs action.
            </p>
          </div>
          <p className="mt-4 md:mt-0 shrink-0 font-mono text-xs uppercase tracking-[0.14em] text-ink-4">
            Change plans when the work changes
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <article className="rounded-lg border border-rule bg-paper-2 p-6 flex flex-col">
            <div className="font-mono text-xs uppercase tracking-[0.18em] text-ink-3 mb-5">
              Fair-code
            </div>
            <h3 className="font-serif text-2xl mb-3">Self-hosted</h3>
            <p className="text-sm text-ink-3 leading-relaxed mb-6">
              Keep the service, dashboard, and execution data in your own environment.
            </p>
            <ul className="space-y-3 text-sm text-ink-2 mb-8">
              <li className="flex gap-2">
                <Check size={16} className="text-evidence shrink-0" />
                Evidence-gated detectors
              </li>
              <li className="flex gap-2">
                <Check size={16} className="text-evidence shrink-0" />
                No hosted account
              </li>
              <li className="flex gap-2">
                <Check size={16} className="text-evidence shrink-0" />
                You control deployment and updates
              </li>
            </ul>
            <a
              href="https://github.com/Pisama-AI/pisama-n8n"
              className="mt-auto inline-block w-fit px-4 py-2 rounded-lg border border-rule text-sm font-medium text-ink-2 hover:text-ink hover:border-ink-4 transition-colors"
            >
              Self-host (fair-code)
            </a>
          </article>

          <article className="rounded-lg border border-rule bg-paper-2 p-6 flex flex-col">
            <div className="font-mono text-xs uppercase tracking-[0.18em] text-ink-3 mb-5">
              Cloud
            </div>
            <h3 className="font-serif text-2xl mb-3">Free</h3>
            <p className="text-sm text-ink-3 leading-relaxed mb-6">
              Get hosted detection and a dashboard for one connected n8n instance.
            </p>
            <ul className="space-y-3 text-sm text-ink-2 mb-8">
              <li className="flex gap-2">
                <Check size={16} className="text-evidence shrink-0" />
                One n8n connection
              </li>
              <li className="flex gap-2">
                <Check size={16} className="text-evidence shrink-0" />
                Evidence-gated detectors
              </li>
              <li className="flex gap-2">
                <Check size={16} className="text-evidence shrink-0" />
                Detection stays free
              </li>
            </ul>
            <a
              href="https://app.n8n.pisama.ai/sign-in"
              className="mt-auto inline-block w-fit px-4 py-2 rounded-lg border border-rule text-sm font-medium text-ink-2 hover:text-ink hover:border-ink-4 transition-colors"
            >
              Start free cloud
            </a>
          </article>

          <article className="rounded-lg border border-evidence bg-paper-3 p-6 flex flex-col shadow-[0_0_0_1px_rgba(232,179,65,0.12)]">
            <div className="flex items-center gap-2 font-mono text-xs uppercase tracking-[0.18em] text-evidence mb-5">
              <Sparkles size={15} /> Pro cloud
            </div>
            <h3 className="font-serif text-2xl mb-3">Fix and approve</h3>
            <p className="text-sm text-ink-2 leading-relaxed mb-6">
              Give a team room to connect more workflows, generate fixes, and apply
              approved changes with a rollback point.
            </p>
            <ul className="space-y-3 text-sm text-ink mb-8">
              <li className="flex gap-2">
                <Check size={16} className="text-evidence shrink-0" />
                Five n8n connections
              </li>
              <li className="flex gap-2">
                <Check size={16} className="text-evidence shrink-0" />
                Monthly AI fix allocation
              </li>
              <li className="flex gap-2">
                <Check size={16} className="text-evidence shrink-0" />
                Apply and roll back approved fixes
              </li>
            </ul>
            <a
              href="https://app.n8n.pisama.ai/sign-in"
              className="mt-auto inline-block w-fit px-4 py-2 rounded-lg bg-evidence text-evidence-ink text-sm font-semibold hover:bg-evidence-2 transition-colors"
            >
              Start free, then upgrade
            </a>
          </article>
        </div>

        <div className="mt-8 overflow-x-auto rounded-lg border border-rule bg-paper">
          <table className="w-full min-w-[660px] text-left text-sm">
            <caption className="sr-only">Comparison of self-host, free cloud, and Pro cloud options</caption>
            <thead className="border-b border-rule text-xs uppercase tracking-[0.14em] text-ink-4">
              <tr>
                <th scope="col" className="px-5 py-4 font-medium">Includes</th>
                <th scope="col" className="px-5 py-4 font-medium">Self-host</th>
                <th scope="col" className="px-5 py-4 font-medium">Free cloud</th>
                <th scope="col" className="px-5 py-4 font-medium text-evidence">Pro cloud</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-rule text-ink-2">
              {PLAN_FEATURES.map(([feature, oss, free, pro]) => (
                <tr key={feature}>
                  <th scope="row" className="px-5 py-4 font-medium text-ink">{feature}</th>
                  <td className="px-5 py-4">{oss}</td>
                  <td className="px-5 py-4">{free}</td>
                  <td className="px-5 py-4 text-ink">{pro}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
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
            <a href="#plans" className="text-ink-3 hover:text-ink transition-colors">
              Compare options
            </a>
            <a
              href="https://github.com/Pisama-AI/pisama-n8n"
              className="text-ink-3 hover:text-ink transition-colors"
            >
              GitHub
            </a>
            <a
              href="https://app.n8n.pisama.ai/sign-in"
              className="px-4 py-2 rounded-lg bg-evidence text-evidence-ink font-medium hover:bg-evidence-2 transition-colors"
            >
              Start free cloud
            </a>
          </nav>
        </div>
      </header>

      {/* hero */}
      <section className="mx-auto max-w-5xl px-6 py-16 md:py-20">
        <div className="grid gap-12 lg:grid-cols-[minmax(0,1fr)_22rem] lg:items-end">
          <div>
            <h1 className="font-serif text-4xl md:text-5xl leading-tight max-w-3xl">
              Your n8n workflows fail quietly.
              <br />
              <span className="text-evidence">This catches them.</span>
            </h1>
            <p className="mt-6 max-w-2xl text-lg text-ink-2 leading-relaxed">
              Pisama reads real workflow executions and surfaces the failures that slip
              through: timeouts, swallowed errors, runaway loops, and exploding payloads.
              Connect your n8n and see the evidence behind each detection.
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-4">
              <a
                href="https://app.n8n.pisama.ai/sign-in"
                className="px-5 py-2.5 rounded-lg bg-evidence text-evidence-ink font-semibold hover:bg-evidence-2 transition-colors"
              >
                Start free cloud
              </a>
              <a
                href="https://github.com/Pisama-AI/pisama-n8n"
                className="px-5 py-2.5 rounded-lg border border-rule text-ink-2 hover:text-ink hover:border-ink-4 transition-colors"
              >
                Self-host (fair-code)
              </a>
              <Link href="#plans" className="text-sm text-ink-3 hover:text-ink transition-colors">
                Compare all options
              </Link>
            </div>
          </div>

          <aside className="border-l border-evidence/70 pl-6 lg:mb-1">
            <SectionLabel>First detection</SectionLabel>
            <ol className="space-y-6">
              {FIRST_DETECTION_STEPS.map((step, index) => (
                <li key={step.title} className="grid grid-cols-[2rem_1fr] gap-3">
                  <span className="font-mono text-xs text-evidence pt-0.5">0{index + 1}</span>
                  <div>
                    <h2 className="font-medium text-sm text-ink">{step.title}</h2>
                    <p className="mt-1 text-sm leading-relaxed text-ink-3">{step.desc}</p>
                  </div>
                </li>
              ))}
            </ol>
          </aside>
        </div>
      </section>

      <PlanComparison />

      {/* detectors */}
      <section className="border-t border-rule bg-paper-2/40">
        <div className="mx-auto max-w-5xl px-6 py-16">
          <SectionLabel>Evidence-gated detectors, two lanes</SectionLabel>
          <h2 className="font-serif text-2xl mb-3">
            Structural analysis of the workflow, runtime analysis of the execution
          </h2>
          <p className="text-ink-3 max-w-2xl mb-10">
            The structural lane reads the workflow graph itself, with precision tuned
            against thousands of real community workflows. The runtime lane reads what
            actually happened in an execution: real timings, real errors, real payload
            sizes, validated on a smaller corpus of real executions.
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
