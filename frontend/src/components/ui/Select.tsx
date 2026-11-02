import type { SelectHTMLAttributes } from 'react'
import { cn } from '../../lib/cn'

export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        'w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-sm text-zinc-100 focus:border-indigo-500 focus:outline-none',
        className,
      )}
      {...props}
    >
      {children}
    </select>
  )
}
