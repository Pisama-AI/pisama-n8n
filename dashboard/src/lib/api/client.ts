// Plain fetch client for the pisama-n8n self-host server. Single-tenant: no BFF
// proxy, no {tenant_id} templating, no next-auth. Bearer key comes from the
// browser's localStorage (a Settings field) or NEXT_PUBLIC_API_KEY at build time.
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8400'

const KEY_STORAGE = 'pisama_n8n_key'

export function resolveKey(): string | undefined {
  // Only touch localStorage in the browser — reading it during SSR throws.
  if (typeof window !== 'undefined') {
    const stored = window.localStorage.getItem(KEY_STORAGE)
    if (stored) return stored
  }
  return process.env.NEXT_PUBLIC_API_KEY || undefined
}

export async function fetchApi<T>(path: string): Promise<T> {
  const key = resolveKey()
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (key) headers.Authorization = `Bearer ${key}`

  const res = await fetch(`${API_BASE}${path}`, { headers })
  if (!res.ok) {
    throw new Error(`GET ${path} failed: ${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<T>
}
