import { clsx } from 'clsx'
import type { ReactNode } from 'react'

interface CardProps {
  children: ReactNode
  className?: string
  hover?: boolean
  onClick?: React.MouseEventHandler<HTMLDivElement>
}

export function Card({ children, className, hover, onClick }: CardProps) {
  return (
    <div className={clsx(hover ? 'card-hover' : 'card', 'p-5', className)} onClick={onClick}>
      {children}
    </div>
  )
}
