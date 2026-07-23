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
import productManifest from '@/data/product-capabilities.generated.json'

export const metadata: Metadata = {
  title: 'Pisama for n8n: failure detection for your workflows',
  description:
    'Compare fair-code self-hosting, Cloud Free, and the Pro preview for n8n failure detection and guarded repairs.',
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
    name: 'Error routing',
    desc: 'A failed execution with no error workflow, or an error route that cannot receive the incident, is surfaced only when the recorded failure proves it.',
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

const PACKAGES = [
  {
    name: 'n8n-nodes-pisama',
    label: 'n8n community node',
    desc: 'Install by package name under n8n Settings, Community Nodes. It signs and sends execution data to hosted or self-hosted Pisama.',
    href: 'https://www.npmjs.com/package/n8n-nodes-pisama',
    cta: 'View on npm',
  },
  {
    name: 'pisama-n8n-engine',
    label: 'Python engine',
    desc: 'Embed the dependency-free structural detector lane directly in a Python service. The source package uses the Pisama Sustainable Use License.',
    href: 'https://github.com/Pisama-AI/pisama-n8n/tree/main/engine',
    cta: 'View engine source',
  },
]

const LAYERED = [
  {
    tag: '$0 · structural',
    title: 'Read the workflow graph',
    desc: 'Cycles with no exit, tangled control flow, a missing error route. Caught from the workflow itself, before an execution ever runs.',
  },
  {
    tag: '$0 · runtime',
    title: 'Read every execution',
    desc: 'Real timings, real errors, real payload sizes. Evidence-gated, so a detection fires only when the recorded run proves it.',
  },
  {
    tag: 'on approval · cloud',
    title: 'Fix only when it is needed',
    desc: 'The cloud tier drafts the fix and applies it once you approve, with a snapshot to roll back. Detection itself stays free.',
  },
]

function productById(id: string) {
  const product = productManifest.products.find((candidate) => candidate.id === id)
  if (!product) throw new Error(`Missing product capability definition: ${id}`)
  return product
}

const CAPABILITY_LABELS = Object.fromEntries(
  productManifest.capabilities.map((capability) => [capability.id, capability.label]),
)
const N8N_SELF_HOSTED = productById('n8n_self_hosted')
const N8N_CLOUD_FREE = productById('n8n_cloud_free')
const N8N_PRO = productById('n8n_pro')

const PLAN_FEATURES = [
  ['Deployment', 'Self-hosted', 'Pisama cloud', 'Pisama cloud'],
  ['Code license', 'Fair-code', 'Hosted service', 'Hosted service'],
  ['Execution data', 'Your environment', 'Pisama-managed', 'Pisama-managed'],
  [
    'n8n connections',
    String(N8N_SELF_HOSTED.allowances.n8n_connections),
    String(N8N_CLOUD_FREE.allowances.n8n_connections),
    String(N8N_PRO.allowances.n8n_connections),
  ],
  [
    CAPABILITY_LABELS.local_heuristic_detection,
    N8N_SELF_HOSTED.capabilities.local_heuristic_detection,
    N8N_CLOUD_FREE.capabilities.local_heuristic_detection,
    N8N_PRO.capabilities.local_heuristic_detection,
  ],
  [
    CAPABILITY_LABELS.evidence_backed_diagnosis,
    N8N_SELF_HOSTED.capabilities.evidence_backed_diagnosis,
    N8N_CLOUD_FREE.capabilities.evidence_backed_diagnosis,
    N8N_PRO.capabilities.evidence_backed_diagnosis,
  ],
  [
    CAPABILITY_LABELS.deterministic_repairs,
    N8N_SELF_HOSTED.capabilities.deterministic_repairs,
    N8N_CLOUD_FREE.capabilities.deterministic_repairs,
    N8N_PRO.capabilities.deterministic_repairs,
  ],
  [
    CAPABILITY_LABELS.model_generated_fixes,
    N8N_SELF_HOSTED.capabilities.model_generated_fixes,
    N8N_CLOUD_FREE.capabilities.model_generated_fixes,
    N8N_PRO.capabilities.model_generated_fixes,
  ],
  [
    CAPABILITY_LABELS.advanced_detection,
    N8N_SELF_HOSTED.capabilities.advanced_detection,
    N8N_CLOUD_FREE.capabilities.advanced_detection,
    N8N_PRO.capabilities.advanced_detection,
  ],
  [
    CAPABILITY_LABELS.managed_operations,
    N8N_SELF_HOSTED.capabilities.managed_operations,
    N8N_CLOUD_FREE.capabilities.managed_operations,
    N8N_PRO.capabilities.managed_operations,
  ],
  [
    CAPABILITY_LABELS.team_governance,
    N8N_SELF_HOSTED.capabilities.team_governance,
    N8N_CLOUD_FREE.capabilities.team_governance,
    N8N_PRO.capabilities.team_governance,
  ],
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
                {CAPABILITY_LABELS.local_heuristic_detection}
              </li>
              <li className="flex gap-2">
                <Check size={16} className="text-evidence shrink-0" />
                No hosted account
              </li>
              <li className="flex gap-2">
                <Check size={16} className="text-evidence shrink-0" />
                {CAPABILITY_LABELS.deterministic_repairs}: guardrails and error routes
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
              Get hosted detection, a dashboard, and deterministic repairs for one
              connected n8n instance.
            </p>
            <ul className="space-y-3 text-sm text-ink-2 mb-8">
              <li className="flex gap-2">
                <Check size={16} className="text-evidence shrink-0" />
                {N8N_CLOUD_FREE.allowances.n8n_connections} n8n connection
              </li>
              <li className="flex gap-2">
                <Check size={16} className="text-evidence shrink-0" />
                {CAPABILITY_LABELS.evidence_backed_diagnosis}
              </li>
              <li className="flex gap-2">
                <Check size={16} className="text-evidence shrink-0" />
                {CAPABILITY_LABELS.deterministic_repairs}: guardrails and error routes
              </li>
            </ul>
            <a
              href="https://app.n8n.pisama.ai/sign-in"
              className="mt-auto inline-block w-fit px-4 py-2 rounded-lg border border-rule text-sm font-medium text-ink-2 hover:text-ink hover:border-ink-4 transition-colors"
            >
              Start free cloud
            </a>
          </article>

          <article className="rounded-lg border border-evidence bg-paper-3 p-6 flex flex-col">
            <div className="flex items-center gap-2 font-mono text-xs uppercase tracking-[0.18em] text-evidence mb-5">
              <Sparkles size={15} /> Pro preview
            </div>
            <h3 className="font-serif text-2xl mb-3">Fix and approve</h3>
            <p className="text-sm text-ink-2 leading-relaxed mb-6">
              Give a team room to connect more workflows, generate fixes, and apply
              approved changes with a rollback point.
            </p>
            <ul className="space-y-3 text-sm text-ink mb-8">
              <li className="flex gap-2">
                <Check size={16} className="text-evidence shrink-0" />
                {N8N_PRO.allowances.n8n_connections} n8n connections
              </li>
              <li className="flex gap-2">
                <Check size={16} className="text-evidence shrink-0" />
                {N8N_PRO.allowances.model_fix_generations_per_month} model-generated fix
                generations each month
              </li>
              <li className="flex gap-2">
                <Check size={16} className="text-evidence shrink-0" />
                Apply and roll back approved fixes
              </li>
            </ul>
            <a
              href="mailto:team@pisama.ai?subject=Pisama%20for%20n8n%20Pro%20access"
              className="mt-auto inline-block w-fit px-4 py-2 rounded-lg bg-evidence text-evidence-ink text-sm font-semibold hover:bg-evidence-2 transition-colors"
            >
              Request Pro access
            </a>
          </article>
        </div>

        <div className="mt-8 overflow-x-auto rounded-lg border border-rule bg-paper">
          <table className="w-full min-w-[660px] text-left text-sm">
            <caption className="sr-only">Comparison of self-host, free cloud, and Pro preview options</caption>
            <thead className="border-b border-rule text-xs uppercase tracking-[0.14em] text-ink-4">
              <tr>
                <th scope="col" className="px-5 py-4 font-medium">Includes</th>
                <th scope="col" className="px-5 py-4 font-medium">Self-host</th>
                <th scope="col" className="px-5 py-4 font-medium">Free cloud</th>
                <th scope="col" className="px-5 py-4 font-medium text-evidence">Pro preview</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-rule text-ink-2">
              {PLAN_FEATURES.map(([feature, selfHosted, free, pro]) => (
                <tr key={feature}>
                  <th scope="row" className="px-5 py-4 font-medium text-ink">{feature}</th>
                  <td className="px-5 py-4">{selfHosted}</td>
                  <td className="px-5 py-4">{free}</td>
                  <td className="px-5 py-4 text-ink">{pro}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-4 text-xs leading-relaxed text-ink-4">
          Self-hosting is free for internal use under the Pisama Sustainable Use
          License. Managed service operation, competing hosted or embedded use,
          and commercial support require a separate agreement.
        </p>
        <a
          href={productManifest.comparison_url}
          className="mt-4 inline-block border-b border-ink pb-0.5 text-sm font-medium text-ink"
        >
          Compare the full Pisama product family
        </a>
      </div>
    </section>
  )
}

export default function Landing() {
  return (
    <main className="min-h-screen bg-paper text-ink">
      {/* nav */}
      <header className="border-b border-rule">
        <div className="mx-auto max-w-5xl px-6 py-5 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3 whitespace-nowrap">
            <PisamaMark size={26} color="var(--ink)" />
            <span className="font-serif text-lg">
              pisama <span className="text-ink-3">for n8n</span>
            </span>
          </div>
          <nav className="flex items-center gap-5 text-sm shrink-0">
            <a href="#plans" className="hidden sm:inline text-ink-3 hover:text-ink transition-colors">
              Compare options
            </a>
            <a
              href="https://github.com/Pisama-AI/pisama-n8n"
              className="hidden sm:inline text-ink-3 hover:text-ink transition-colors"
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
              Free deterministic repairs can add guards and error routes after approval.
              Pro adds model-generated fixes for the failures that need more context.
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

      {/* why layered: catch early, catch cheap */}
      <section className="border-t border-rule">
        <div className="mx-auto max-w-5xl px-6 py-16">
          <SectionLabel>Catch it early, catch it cheap</SectionLabel>
          <h2 className="font-serif text-2xl mb-3 max-w-2xl">
            Cheap checks run first. An AI fix runs only when a detection needs one.
          </h2>
          <p className="text-ink-3 max-w-2xl mb-10">
            Waiting for a failed run to tell you something went wrong is the expensive way
            to learn it. Both detection lanes are free and evidence-gated, so Pisama reads
            every workflow and every execution up front, then saves the paid AI fix for the
            detections that actually need action.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {LAYERED.map((step, index) => (
              <div key={step.title} className="rounded-lg border border-rule bg-paper-2 p-5">
                <div className="flex items-baseline justify-between gap-3 mb-3">
                  <span className="font-mono text-xs text-evidence">0{index + 1}</span>
                  <span className="font-mono text-[11px] uppercase tracking-[0.12em] text-ink-4">
                    {step.tag}
                  </span>
                </div>
                <div className="font-semibold text-sm mb-1.5">{step.title}</div>
                <p className="text-sm text-ink-3 leading-relaxed">{step.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* channels */}
      <section className="border-t border-rule bg-paper-2/40">
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

      {/* packages */}
      <section className="border-t border-rule">
        <div className="mx-auto max-w-5xl px-6 py-16">
          <SectionLabel>Packages</SectionLabel>
          <h2 className="font-serif text-2xl mb-3">Use the integration or embed the engine</h2>
          <p className="text-ink-3 max-w-2xl mb-10">
            The community node delivers executions to Pisama. The Python engine runs
            detection inside your own application. They are independent packages, so
            install only the surface your deployment needs.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {PACKAGES.map((pkg) => (
              <article key={pkg.name} className="rounded-lg border border-rule bg-paper p-6">
                <div className="font-mono text-xs uppercase tracking-[0.16em] text-evidence">
                  {pkg.label}
                </div>
                <h3 className="mt-3 font-mono text-base text-ink">{pkg.name}</h3>
                <p className="mt-3 text-sm text-ink-3 leading-relaxed">{pkg.desc}</p>
                <a
                  href={pkg.href}
                  className="mt-5 inline-block text-sm text-evidence hover:underline"
                >
                  {pkg.cta}
                </a>
              </article>
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
            <a
              href="https://github.com/Pisama-AI/pisama-n8n/tree/main/engine"
              className="hover:text-ink-2 transition-colors"
            >
              Python engine
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
