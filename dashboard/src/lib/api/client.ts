// Plain fetch client. Two modes:
//   OSS self-host (default): direct calls to the server, bearer key from
//   localStorage (Settings) or NEXT_PUBLIC_API_KEY. Single-tenant.
//   SaaS (NEXT_PUBLIC_SAAS=1): same-origin BFF proxy (/api/backend) — the session
//   cookie authenticates, the proxy attaches the tenant JWT server-side, and no
//   key exists in the browser at all.
import { IS_SAAS } from '@/lib/saas'

export const API_BASE = IS_SAAS
  ? '/api/backend'
  : process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8400'

const KEY_STORAGE = 'pisama_n8n_key'

export function resolveKey(): string | undefined {
  if (IS_SAAS) return undefined // session cookie + BFF, never a client-side key
  // Only touch localStorage in the browser — reading it during SSR throws.
  if (typeof window !== 'undefined') {
    const stored = window.localStorage.getItem(KEY_STORAGE)
    if (stored) return stored
  }
  return process.env.NEXT_PUBLIC_API_KEY || undefined
}

// OSS self-host: persist / clear the bearer key the dashboard sends on POSTs
// (used when the server sets PISAMA_API_KEY). Set from the Settings page.
export function setStoredKey(key: string): void {
  if (typeof window !== 'undefined') window.localStorage.setItem(KEY_STORAGE, key)
}

export function clearStoredKey(): void {
  if (typeof window !== 'undefined') window.localStorage.removeItem(KEY_STORAGE)
}

export function hasStoredKey(): boolean {
  return typeof window !== 'undefined' && Boolean(window.localStorage.getItem(KEY_STORAGE))
}

// SaaS mode: a 401 from the BFF means the session is beyond repair (the proxy
// already retried a server-side token refresh) — send the user to sign-in
// instead of a dead-end "couldn't reach the server" card.
function redirectToSignIn(): void {
  if (!IS_SAAS || typeof window === 'undefined') return
  if (window.location.pathname.startsWith('/sign-in')) return
  const callbackUrl = encodeURIComponent(window.location.pathname + window.location.search)
  window.location.assign(`/sign-in?callbackUrl=${callbackUrl}`)
}

export async function fetchApi<T>(path: string): Promise<T> {
  const key = resolveKey()
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (key) headers.Authorization = `Bearer ${key}`

  const res = await fetch(`${API_BASE}${path}`, { headers })
  if (!res.ok) {
    if (res.status === 401) redirectToSignIn()
    throw new Error(`GET ${path} failed: ${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<T>
}

export async function postApi<T>(path: string, body: unknown): Promise<T> {
  const key = resolveKey()
  const headers: Record<string, string> = {
    Accept: 'application/json',
    'Content-Type': 'application/json',
  }
  if (key) headers.Authorization = `Bearer ${key}`

  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    if (res.status === 401) redirectToSignIn()
    // 402 = paid feature not configured; surface it distinctly.
    const err = new Error(`POST ${path} failed: ${res.status}`)
    ;(err as Error & { status?: number }).status = res.status
    throw err
  }
  return res.json() as Promise<T>
}
