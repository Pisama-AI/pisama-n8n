import { cn } from '@/lib/utils'
import type { LucideIcon } from 'lucide-react'

interface StatCardProps {
  icon: LucideIcon
  label: string
  value: string | number
  color: string
  bgColor: string
}

export function StatCard({ icon: Icon, label, value, color, bgColor }: StatCardProps) {
  return (
    <div className="p-4 rounded-xl bg-paper-2/50 border border-rule">
      <div className="flex items-center gap-3">
        <div className={cn('p-2 rounded-lg', bgColor)}>
          <Icon size={18} className={color} />
        </div>
        <div>
          <div className="text-2xl font-bold text-ink">{value}</div>
          <div className="text-xs text-ink-3">{label}</div>
        </div>
      </div>
    </div>
  )
}
