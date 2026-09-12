import { clsx } from 'clsx'
import type { ReactNode } from 'react'

interface BadgeProps {
  children: ReactNode
  variant?: 'brand' | 'accent' | 'green' | 'yellow' | 'red' | 'slate'
  className?: string
}

const variantClasses = {
  brand:  'bg-brand-500/15 text-brand-300 border border-brand-500/25',
  accent: 'bg-accent-500/15 text-accent-300 border border-accent-500/25',
  green:  'bg-emerald-500/15 text-emerald-300 border border-emerald-500/25',
  yellow: 'bg-amber-500/15 text-amber-300 border border-amber-500/25',
  red:    'bg-red-500/15 text-red-300 border border-red-500/25',
  slate:  'bg-slate-500/15 text-slate-300 border border-slate-500/25',
}

export function Badge({ children, variant = 'slate', className }: BadgeProps) {
  return (
    <span className={clsx('badge', variantClasses[variant], className)}>
      {children}
    </span>
  )
}
