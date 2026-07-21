// SaaS-mode switch. OFF (default): the OSS self-host dashboard, byte-identical
// behavior — direct API calls with a bearer key. ON (NEXT_PUBLIC_SAAS=1, the
// hosted app.n8n.pisama.ai deployment): Google sign-in via NextAuth and all API
// calls through the same-origin BFF proxy, which attaches the backend JWT
// server-side so no credential ever reaches client JS.
export const IS_SAAS = process.env.NEXT_PUBLIC_SAAS === '1'

// The PUBLIC API origin push callers use (community node credential "API URL",
// direct webhook POSTs). The BFF hides the origin from browser calls, but a
// user wiring the n8n community node needs the real host, so Settings shows it.
export const SAAS_PUBLIC_API_URL =
  process.env.NEXT_PUBLIC_SAAS_PUBLIC_API_URL || 'https://pisama-n8n-cloud.fly.dev'
