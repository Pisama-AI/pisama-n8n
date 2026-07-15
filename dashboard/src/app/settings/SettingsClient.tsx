'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { signOut } from 'next-auth/react'
import { formatDistanceToNow } from 'date-fns'
import { KeyRound, RefreshCw, Sparkles, LogOut, Plus, Server, Cable } from 'lucide-react'
import { Layout } from '@/components/common/Layout'
import { Card, CardHeader, CardTitle, Button, Input, EmptyState } from '@/components/ui'
import { Skeleton } from '@/components/ui/Skeleton'
import { IS_SAAS } from '@/lib/saas'
import { BILLING_ENABLED } from '@/lib/flags'
import { API_BASE, setStoredKey, clearStoredKey, hasStoredKey } from '@/lib/api/client'
import {
  getMe,
  listConnections,
  syncConnection,
  syncOss,
  openBillingPortal,
} from '@/lib/api/settings'
import { getPaidStatus } from '@/lib/api/fixes'

function CardTitleRow({ icon: Icon, children }: { icon: React.ElementType; children: React.ReactNode }) {
  return (
    <CardHeader className="mb-3">
      <div className="flex items-center gap-2">
        <Icon size={16} className="text-evidence" />
        <CardTitle>{children}</CardTitle>
      </div>
    </CardHeader>
  )
}

// ── OSS self-host cards ─────────────────────────────────────────────────────

// The one real gap: the dashboard reads a bearer key from localStorage but had no
// way to set it. Needed when the server runs with PISAMA_API_KEY.
function ApiKeyCard() {
  const qc = useQueryClient()
  const [value, setValue] = useState('')
  const [saved, setSaved] = useState(false)
  useEffect(() => setSaved(hasStoredKey()), [])

  return (
    <Card padding="lg">
      <CardTitleRow icon={KeyRound}>Dashboard API key</CardTitleRow>
      <p className="text-sm text-ink-3 mb-4">
        If your server sets <code className="text-ink-2">PISAMA_API_KEY</code>, paste it here so the
        dashboard can trigger syncs and fixes. Stored only in this browser, never sent anywhere else.
      </p>
      <div className="flex gap-2">
        <Input
          type="password"
          placeholder={saved ? '•••••••• saved' : 'pisama_...'}
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
        <Button
          size="sm"
          disabled={!value.trim()}
          onClick={() => {
            setStoredKey(value.trim())
            setValue('')
            setSaved(true)
            qc.invalidateQueries()
          }}
        >
          Save
        </Button>
        {saved && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              clearStoredKey()
              setSaved(false)
              qc.invalidateQueries()
            }}
          >
            Clear
          </Button>
        )}
      </div>
      {saved && (
        <p className="mt-2 text-xs" style={{ color: 'var(--pass)' }}>
          A key is saved in this browser.
        </p>
      )}
    </Card>
  )
}

function SyncCard() {
  const qc = useQueryClient()
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)

  async function onSync() {
    setBusy(true)
    setMsg(null)
    try {
      const summary = await syncOss()
      qc.invalidateQueries({ queryKey: ['detections'] })
      setMsg({ ok: true, text: `Ingested ${summary.new ?? 0} new execution(s).` })
    } catch (e) {
      const status = (e as Error & { status?: number }).status
      setMsg({
        ok: false,
        text:
          status === 400
            ? 'Polling is not configured — set PISAMA_N8N_URL and PISAMA_N8N_API_KEY on the server.'
            : status === 401
            ? 'Unauthorized — check the API key above.'
            : 'Sync failed. Check the server logs.',
      })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card padding="lg">
      <CardTitleRow icon={Cable}>n8n connection</CardTitleRow>
      <p className="text-sm text-ink-3 mb-4">
        On a self-host server the n8n connection is configured with environment variables
        (<code className="text-ink-2">PISAMA_N8N_URL</code> +{' '}
        <code className="text-ink-2">PISAMA_N8N_API_KEY</code>). Pull recent executions now:
      </p>
      <Button size="sm" onClick={onSync} isLoading={busy} leftIcon={<RefreshCw size={14} />}>
        Sync now
      </Button>
      {msg && (
        <p className="mt-3 text-sm" style={{ color: msg.ok ? 'var(--pass)' : 'var(--fail)' }}>
          {msg.text}
        </p>
      )}
    </Card>
  )
}

function PaidStatusCard() {
  const { data, isLoading } = useQuery({ queryKey: ['paid-status'], queryFn: getPaidStatus })

  return (
    <Card padding="lg">
      <CardTitleRow icon={Sparkles}>AI fixes</CardTitleRow>
      {isLoading ? (
        <Skeleton className="h-5 w-40" />
      ) : data?.enabled ? (
        <p className="text-sm" style={{ color: 'var(--pass)' }}>
          Cloud fix suggestions are configured on this server.
        </p>
      ) : (
        <p className="text-sm text-ink-3">
          Not configured. Set <code className="text-ink-2">PISAMA_CLOUD_KEY</code> on the server to
          enable AI fix suggestions.
        </p>
      )}
    </Card>
  )
}

function ServerCard() {
  return (
    <Card padding="lg">
      <CardTitleRow icon={Server}>Server</CardTitleRow>
      <div className="text-sm text-ink-3">
        API base <code className="text-ink-2 break-all">{API_BASE}</code>
      </div>
    </Card>
  )
}

// ── SaaS (hosted) cards ─────────────────────────────────────────────────────

function AccountCard() {
  const { data, isLoading } = useQuery({ queryKey: ['me'], queryFn: getMe, staleTime: 60_000 })

  return (
    <Card padding="lg">
      <CardTitleRow icon={KeyRound}>Account</CardTitleRow>
      {isLoading ? (
        <Skeleton className="h-10 w-56" />
      ) : (
        <div className="flex items-center justify-between">
          <div>
            <div className="text-sm text-ink">{data?.name ?? '—'}</div>
            <div className="mt-1 inline-flex items-center gap-1.5 text-xs text-ink-3">
              <span className="font-mono uppercase tracking-wide">{(data?.plan || 'free').toUpperCase()}</span>{' '}
              plan
            </div>
          </div>
          <Button
            size="sm"
            variant="ghost"
            leftIcon={<LogOut size={14} />}
            onClick={() => signOut({ callbackUrl: '/sign-in' })}
          >
            Sign out
          </Button>
        </div>
      )}
    </Card>
  )
}

function ConnectionsCard() {
  const qc = useQueryClient()
  const { data, isLoading, isError } = useQuery({ queryKey: ['connections'], queryFn: listConnections })
  const [syncingId, setSyncingId] = useState<string | null>(null)

  async function onSync(id: string) {
    setSyncingId(id)
    try {
      await syncConnection(id)
      qc.invalidateQueries({ queryKey: ['detections'] })
      qc.invalidateQueries({ queryKey: ['connections'] })
    } finally {
      setSyncingId(null)
    }
  }

  return (
    <Card padding="lg">
      <CardTitleRow icon={Cable}>Connections</CardTitleRow>
      {isLoading ? (
        <Skeleton className="h-16" />
      ) : isError ? (
        <p className="text-sm text-ink-3">Couldn&apos;t load connections.</p>
      ) : !data || data.length === 0 ? (
        <EmptyState
          title="No n8n connected"
          description="Connect your n8n to start catching failures."
          action={
            <Link href="/onboarding">
              <Button size="sm" leftIcon={<Plus size={14} />}>Connect n8n</Button>
            </Link>
          }
        />
      ) : (
        <div className="space-y-3">
          {data.map((c) => (
            <div key={c.id} className="flex items-center gap-3 rounded-lg border border-rule p-3">
              <span
                aria-hidden
                className="w-2 h-2 rounded-full"
                style={{ background: c.active ? 'var(--pass)' : 'var(--ink-4)' }}
              />
              <div className="flex-1 min-w-0">
                <div className="text-sm text-ink truncate">{c.base_url}</div>
                <div className="text-xs text-ink-3">
                  {c.last_error ? (
                    <span style={{ color: 'var(--fail)' }}>{c.last_error}</span>
                  ) : c.last_polled_at ? (
                    `Last synced ${formatDistanceToNow(new Date(c.last_polled_at), { addSuffix: true })}`
                  ) : (
                    'Not synced yet'
                  )}
                </div>
              </div>
              <Button
                size="sm"
                variant="ghost"
                isLoading={syncingId === c.id}
                leftIcon={<RefreshCw size={14} />}
                onClick={() => onSync(c.id)}
              >
                Sync
              </Button>
            </div>
          ))}
          <Link href="/onboarding" className="inline-flex items-center gap-1.5 text-sm text-evidence hover:underline">
            <Plus size={14} /> Connect another instance
          </Link>
        </div>
      )}
    </Card>
  )
}

function BillingCard() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function onManage() {
    setBusy(true)
    setError(null)
    try {
      window.location.href = await openBillingPortal()
    } catch {
      setError('Could not open the billing portal. Try again.')
      setBusy(false)
    }
  }

  return (
    <Card padding="lg">
      <CardTitleRow icon={Sparkles}>Billing</CardTitleRow>
      <p className="text-sm text-ink-3 mb-4">
        Manage your subscription, payment method, and invoices in the Stripe portal.
      </p>
      <Button size="sm" variant="secondary" isLoading={busy} onClick={onManage}>
        Manage subscription
      </Button>
      {error && <p className="mt-2 text-sm" style={{ color: 'var(--fail)' }}>{error}</p>}
    </Card>
  )
}

export function SettingsClient() {
  return (
    <Layout title="Settings">
      <div className="mx-auto max-w-3xl space-y-6">
        <div>
          <h2 className="font-serif text-2xl text-ink">Settings</h2>
          <p className="text-sm text-ink-3 mt-1">
            {IS_SAAS
              ? 'Your account, connections, and billing.'
              : 'Connection and access for this self-hosted instance.'}
          </p>
        </div>

        {IS_SAAS ? (
          <>
            <AccountCard />
            <ConnectionsCard />
            {BILLING_ENABLED && <BillingCard />}
          </>
        ) : (
          <>
            <ApiKeyCard />
            <SyncCard />
            <PaidStatusCard />
            <ServerCard />
          </>
        )}
      </div>
    </Layout>
  )
}
