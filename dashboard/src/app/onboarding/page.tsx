'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { Cable, Loader2 } from 'lucide-react'
import { PisamaMark } from '@/components/common/PisamaMark'
import { postApi } from '@/lib/api/client'

// Onboarding: connect the tenant's own n8n. The API key goes straight through the
// BFF to the server, is validated with a real n8n call, stored encrypted, and never
// comes back to the browser.
export default function Onboarding() {
  const router = useRouter()
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [state, setState] = useState<'idle' | 'connecting' | 'syncing'>('idle')
  const [error, setError] = useState<string | null>(null)

  async function onConnect(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setState('connecting')
    try {
      const conn = await postApi<{ id: string }>('/api/v1/connections', {
        base_url: baseUrl.trim(),
        api_key: apiKey.trim(),
      })
      setState('syncing')
      // First sync so the dashboard has real detections the moment it loads.
      await postApi(`/api/v1/connections/${conn.id}/sync`, {})
      router.push('/overview')
    } catch (err) {
      const status = (err as Error & { status?: number }).status
      setError(
        status === 422
          ? 'Could not connect: check the n8n URL and that the API key is valid.'
          : 'Connection failed. Check the URL and try again.',
      )
      setState('idle')
    }
  }

  return (
    <main className="min-h-screen bg-paper text-ink flex items-center justify-center px-6">
      <div className="w-full max-w-lg rounded-lg border border-rule bg-paper-2 p-8">
        <div className="flex items-center gap-3 mb-2">
          <PisamaMark size={24} color="var(--ink)" />
          <h1 className="font-serif text-xl">Connect your n8n</h1>
        </div>
        <p className="text-sm text-ink-3 mb-8">
          Pisama polls your n8n for recent executions and detects the failures that slip
          through. Read-only access; no workflow edits. Your API key is stored encrypted
          and never shown again.
        </p>

        <form onSubmit={onConnect} className="space-y-5">
          <div>
            <label className="block text-xs uppercase tracking-wide text-ink-3 mb-1.5">
              n8n instance URL
            </label>
            <input
              type="url"
              required
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://your-team.app.n8n.cloud"
              className="w-full rounded-lg border border-rule bg-paper px-3 py-2 text-sm text-ink placeholder:text-ink-4 focus:outline-none focus:border-evidence"
            />
          </div>
          <div>
            <label className="block text-xs uppercase tracking-wide text-ink-3 mb-1.5">
              n8n API key
            </label>
            <input
              type="password"
              required
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="n8n_api_..."
              className="w-full rounded-lg border border-rule bg-paper px-3 py-2 text-sm text-ink placeholder:text-ink-4 focus:outline-none focus:border-evidence"
            />
            <p className="mt-1.5 text-xs text-ink-4">
              n8n → Settings → API. Cloud and self-hosted both work.
            </p>
          </div>

          {error && (
            <p className="text-sm" style={{ color: 'var(--fail)' }}>
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={state !== 'idle'}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-evidence text-evidence-ink font-semibold hover:bg-evidence-2 transition-colors disabled:opacity-60"
          >
            {state === 'idle' ? (
              <>
                <Cable size={15} /> Connect and analyze
              </>
            ) : (
              <>
                <Loader2 size={15} className="animate-spin" />
                {state === 'connecting' ? 'Validating connection…' : 'Analyzing recent executions…'}
              </>
            )}
          </button>
        </form>
      </div>
    </main>
  )
}
