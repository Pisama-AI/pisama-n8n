'use client'

import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { signOut } from 'next-auth/react'
import { PisamaMark } from '@/components/common/PisamaMark'
import { IS_SAAS } from '@/lib/saas'
import { fetchApi } from '@/lib/api/client'

interface HeaderProps {
  onMenuClick?: () => void
  title?: string
}

interface Me {
  name?: string // the tenant name — for SaaS tenants this is the sign-in email
  plan?: string
}

// The right-side indicator. OSS self-host shows a static "Self-host" pill; the hosted
// SaaS build (NEXT_PUBLIC_SAAS=1) shows the signed-in account's plan + email + sign out.
function StatusPill() {
  const { data } = useQuery<Me>({
    queryKey: ['me'],
    queryFn: () => fetchApi('/api/v1/me'),
    enabled: IS_SAAS, // build-time constant; the query never runs in OSS mode
    staleTime: 60_000,
  })

  const pillStyle = {
    fontFamily: 'var(--font-mono)',
    fontSize: 10,
    letterSpacing: '.12em',
    textTransform: 'uppercase' as const,
    color: 'var(--ink-2)',
    borderColor: 'var(--rule)',
    background: 'transparent',
  }
  const dot = (
    <span
      aria-hidden
      style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--evidence)', display: 'inline-block' }}
    />
  )

  if (!IS_SAAS) {
    return (
      <span className="hidden sm:inline-flex items-center gap-1.5 px-2 py-0.5 border" style={pillStyle}>
        {dot}
        Self-host
      </span>
    )
  }

  const plan = (data?.plan || 'free').toUpperCase()
  const email = data?.name

  return (
    <div className="flex items-center gap-3">
      {email && (
        <span className="hidden md:inline text-xs" style={{ color: 'var(--ink-3)' }}>
          {email}
        </span>
      )}
      <span className="hidden sm:inline-flex items-center gap-1.5 px-2 py-0.5 border" style={pillStyle}>
        {dot}
        {plan}
      </span>
      <button
        onClick={() => signOut({ callbackUrl: '/sign-in' })}
        className="text-xs text-ink-3 hover:text-ink transition-colors"
      >
        Sign out
      </button>
    </div>
  )
}

export function Header({ onMenuClick, title }: HeaderProps) {
  return (
    <header className="flex items-center justify-between h-14 px-6 bg-paper border-b border-rule">
      <div className="flex items-center gap-4">
        {onMenuClick && (
          <button
            onClick={onMenuClick}
            className="p-2 min-h-[44px] min-w-[44px] flex items-center justify-center text-ink-3 hover:text-ink hover:bg-paper-2 rounded lg:hidden"
            aria-label="Open navigation menu"
          >
            <span aria-hidden className="text-xl leading-none">≡</span>
          </button>
        )}
        <Link
          href="/"
          prefetch={false}
          className="lg:hidden inline-flex items-center gap-2"
          style={{
            fontFamily: 'var(--font-serif)',
            fontSize: 18,
            fontWeight: 500,
            letterSpacing: '-.01em',
            color: 'var(--ink)',
            textDecoration: 'none',
          }}
        >
          <PisamaMark size={22} color="var(--ink)" />
          pisama
        </Link>
        {title && (
          <h1
            style={{
              fontFamily: 'var(--font-serif)',
              fontSize: 18,
              fontWeight: 500,
              color: 'var(--ink)',
              letterSpacing: '-.01em',
            }}
          >
            {title}
          </h1>
        )}
      </div>

      <div className="flex items-center gap-3">
        <StatusPill />
      </div>
    </header>
  )
}
