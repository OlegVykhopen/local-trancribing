import type { ButtonHTMLAttributes } from 'react'
import { cn } from '../../lib/cn'

type Variant = 'ghost' | 'danger'

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** Accessible name; also shown as the native tooltip. */
  label: string
  variant?: Variant
}

const variantClasses: Record<Variant, string> = {
  ghost: 'text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100',
  danger: 'text-zinc-400 hover:bg-red-500/10 hover:text-red-400',
}

export function IconButton({ label, variant = 'ghost', className, type = 'button', ...props }: IconButtonProps) {
  return (
    <button
      type={type}
      aria-label={label}
      title={label}
      className={cn(
        'inline-flex size-8 shrink-0 items-center justify-center rounded-md transition-colors disabled:cursor-not-allowed disabled:opacity-50',
        variantClasses[variant],
        className,
      )}
      {...props}
    />
  )
}
