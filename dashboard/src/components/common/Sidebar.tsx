'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { cn } from '@/lib/utils'
import { LayoutDashboard, AlertTriangle, Settings } from 'lucide-react'
import { PisamaMark } from '@/components/common/PisamaMark'

interface NavItem {
  label: string
  href: string
  icon: React.ElementType
}

const navItems: NavItem[] = [
  { label: 'Overview', href: '/overview', icon: LayoutDashboard },
  { label: 'Detections', href: '/detections', icon: AlertTriangle },
  { label: 'Settings', href: '/settings', icon: Settings },
]

function NavLink({ item, pathname }: { item: NavItem; pathname: string | null }) {
  const isActive =
    pathname === item.href ||
    (item.href !== '/' && pathname?.startsWith(item.href + '/'))
  const Icon = item.icon

  return (
    <Link
      href={item.href}
      className={cn(
        'flex items-center gap-3 px-3 py-2 text-sm transition-colors duration-150 border-l-2 -ml-px',
        isActive
          ? 'bg-paper text-ink border-evidence'
          : 'text-ink-3 hover:bg-paper hover:text-ink border-transparent'
      )}
    >
      <Icon size={18} />
      <span className="flex-1">{item.label}</span>
    </Link>
  )
}

export function Sidebar() {
  const pathname = usePathname()

  return (
    <aside
      aria-label="Sidebar"
      className="flex flex-col bg-paper-2 border-r border-rule w-60"
    >
      {/* Logo */}
      <div className="flex items-center h-14 px-4 border-b border-rule">
        <Link
          href="/"
          prefetch={false}
          className="flex items-center gap-2"
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
          <span>pisama</span>
        </Link>
      </div>

      {/* Navigation */}
      <nav aria-label="Main navigation" className="flex-1 overflow-y-auto p-3 space-y-0.5">
        {navItems.map((item) => (
          <NavLink key={item.href} item={item} pathname={pathname} />
        ))}
      </nav>
    </aside>
  )
}
