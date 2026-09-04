import clsx from 'clsx'
import type { ReactNode } from 'react'

export type StatTone = 'neutral' | 'ok' | 'warn' | 'bad' | 'accent'

const TONES: Record<StatTone, { value: string; icon: string; rule: string }> = {
  neutral: { value: 'text-ink', icon: 'text-ink-faint bg-base-800', rule: 'bg-base-600' },
  ok: { value: 'text-emerald-300', icon: 'text-emerald-300 bg-emerald-500/10', rule: 'bg-emerald-500/70' },
  warn: { value: 'text-amber-300', icon: 'text-amber-300 bg-amber-500/10', rule: 'bg-amber-500/70' },
  bad: { value: 'text-red-300', icon: 'text-red-300 bg-red-500/10', rule: 'bg-red-500/80' },
  accent: { value: 'text-sky-300', icon: 'text-sky-300 bg-sky-500/10', rule: 'bg-sky-500/70' },
}

interface StatCardProps {
  label: string
  value: ReactNode
  unit?: string
  hint?: ReactNode
  icon?: ReactNode
  tone?: StatTone
  /** Applies a one-shot attention animation, e.g. when a new attack lands. */
  pulse?: boolean
  className?: string
}

/** A single headline metric. The dashboard's top row is built from these. */
export function StatCard({
  label,
  value,
  unit,
  hint,
  icon,
  tone = 'neutral',
  pulse = false,
  className,
}: StatCardProps) {
  const palette = TONES[tone]
  return (
    <div
      className={clsx(
        'relative overflow-hidden rounded-xl border border-base-700/80 bg-base-850/70 bg-panel-sheen p-4 shadow-panel',
        pulse && 'animate-pulse-ring',
        className,
      )}
    >
      <span className={clsx('absolute inset-x-0 top-0 h-px', palette.rule)} aria-hidden="true" />
      <div className="flex items-start justify-between gap-3">
        <p className="text-2xs font-medium uppercase tracking-wider text-ink-faint">{label}</p>
        {icon && (
          <span className={clsx('rounded-md p-1.5', palette.icon)} aria-hidden="true">
            {icon}
          </span>
        )}
      </div>
      <p className="mt-2 flex items-baseline gap-1.5">
        <span className={clsx('font-mono text-2xl font-semibold tabular-nums', palette.value)}>
          {value}
        </span>
        {unit && <span className="text-xs text-ink-faint">{unit}</span>}
      </p>
      {hint && <p className="mt-1 truncate text-xs text-ink-muted">{hint}</p>}
    </div>
  )
}
