'use client'

import Link from 'next/link'
import { PisamaMark } from '@/components/common/PisamaMark'

interface HeaderProps {
  onMenuClick?: () => void
  title?: string
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
        <span
          className="hidden sm:inline-flex items-center gap-1.5 px-2 py-0.5 border"
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 10,
            letterSpacing: '.12em',
            textTransform: 'uppercase',
            color: 'var(--ink-2)',
            borderColor: 'var(--rule)',
            background: 'transparent',
          }}
        >
          <span
            aria-hidden
            style={{
              width: 6,
              height: 6,
              borderRadius: '50%',
              background: 'var(--evidence)',
              display: 'inline-block',
            }}
          />
          Self-host
        </span>
      </div>
    </header>
  )
}
