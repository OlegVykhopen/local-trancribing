import { motion } from 'motion/react'
import { cn } from '../lib/cn'

const INDETERMINATE_STAGES = new Set(['aligning', 'diarizing', 'postprocessing', 'loading_model'])

interface ProgressBarProps {
  percent: number | null
  stage: string
}

export function ProgressBar({ percent, stage }: ProgressBarProps) {
  const indeterminate = percent === null || (percent === 0 && INDETERMINATE_STAGES.has(stage))

  return (
    <div
      data-testid="progress-bar"
      className="relative h-2 w-full overflow-hidden rounded-full bg-zinc-800"
    >
      {indeterminate ? (
        <motion.div
          data-testid="progress-bar-indeterminate"
          className="absolute inset-y-0 w-1/3 rounded-full bg-indigo-500"
          animate={{ x: ['-100%', '300%'] }}
          transition={{ duration: 1.2, repeat: Infinity, ease: 'linear' }}
        />
      ) : (
        <motion.div
          data-testid="progress-bar-fill"
          className={cn('h-full rounded-full bg-indigo-500')}
          initial={{ width: 0 }}
          animate={{ width: `${Math.min(100, Math.max(0, percent))}%` }}
          transition={{ type: 'spring', stiffness: 120, damping: 20 }}
        />
      )}
    </div>
  )
}
