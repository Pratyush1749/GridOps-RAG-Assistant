import { clsx } from 'clsx'
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { Spinner } from './Spinner'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'ghost' | 'danger'
  loading?: boolean
  children: ReactNode
}

export function Button({ variant = 'primary', loading, children, className, disabled, ...rest }: ButtonProps) {
  const cls = {
    primary: 'btn-primary',
    ghost:   'btn-ghost',
    danger:  'btn-danger',
  }[variant]

  return (
    <button
      className={clsx(cls, className)}
      disabled={disabled || loading}
      {...rest}
    >
      {loading && <Spinner size="sm" />}
      {children}
    </button>
  )
}
