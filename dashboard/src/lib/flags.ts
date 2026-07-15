// User-facing feature flags.
//
// These gate surfaces that aren't ready to be exposed at this stage of the
// product (see the FE scoring review). All are default-OFF and flipped via
// NEXT_PUBLIC_* env at build time.
//
//   HEALING_APPLY  — auto-apply a generated fix to the user's LIVE n8n workflow.
//                    Fix *suggestions* stay on; only the write-side mutation is
//                    gated until fix quality is validated. A self-hoster who
//                    wants it sets NEXT_PUBLIC_HEALING_APPLY=1.
//   BILLING        — the paid "Upgrade to Pro" / Stripe checkout CTA. Off until
//                    we're charging real money (Stripe is still test-mode).

export const HEALING_APPLY_ENABLED = process.env.NEXT_PUBLIC_HEALING_APPLY === '1'
export const BILLING_ENABLED = process.env.NEXT_PUBLIC_BILLING === '1'

// Optional: the user's own n8n base URL, so detection detail can deep-link to
// the real execution. Self-host only; unset → no link is rendered (never a
// broken one). e.g. https://your-team.app.n8n.cloud
export const N8N_BASE_URL = process.env.NEXT_PUBLIC_N8N_BASE_URL || ''
