// SaaS-mode switch. OFF (default): the OSS self-host dashboard, byte-identical
// behavior — direct API calls with a bearer key. ON (NEXT_PUBLIC_SAAS=1, the
// hosted app.n8n.pisama.ai deployment): Google sign-in via NextAuth and all API
// calls through the same-origin BFF proxy, which attaches the backend JWT
// server-side so no credential ever reaches client JS.
export const IS_SAAS = process.env.NEXT_PUBLIC_SAAS === '1'
