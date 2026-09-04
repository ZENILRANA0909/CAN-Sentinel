import clsx from 'clsx'
import type { ReactNode } from 'react'
import { severityTone, threatTone } from '@/utils/format'
import type { Severity, ThreatLevel } from '@/types/api'

interface BadgeProps {
  children: ReactNode
  className?: string
  title?: string
}

function BaseBadge({ children, className, title }: BadgeProps) {
  return (
    <span
      title={title}
      className={clsx(
        'inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-2xs font-semibold uppercase tracking-wide',
        className,
      )}
    >
      {children}
    </span>
  )
}

export function SeverityBadge({ severity }: { severity: Severity | string }) {
  const tone = severityTone(severity)
  return (
    <BaseBadge className={tone.badge} title={`Severity: ${tone.label}`}>
      {tone.label}
    </BaseBadge>
  )
}

export function ThreatBadge({ level }: { level: ThreatLevel | string }) {
  const tone = threatTone(level)
  return (
    <BaseBadge className={tone.badge} title={`Threat level: ${tone.label}`}>
      {tone.label}
    </BaseBadge>
  )
}

export type StatusKind = 'ok' | 'warn' | 'bad' | 'idle' | 'busy'

const STATUS_STYLES: Record<StatusKind, { dot: string; text: string }> = {
  ok: { dot: 'bg-state-ok', text: 'text-emerald-300' },
  warn: { dot: 'bg-state-warn', text: 'text-amber-300' },
  bad: { dot: 'bg-state-bad', text: 'text-red-300' },
  idle: { dot: 'bg-state-idle', text: 'text-ink-muted' },
  busy: { dot: 'bg-accent', text: 'text-sky-300' },
}

interface StatusBadgeProps {
  kind: StatusKind
  label: string
  /** Adds a soft pulse, for a live/connected indicator. */
  live?: boolean
  className?: string
}

/**
 * A dot plus a word. The dot alone would encode meaning in colour only, which
 * fails for colour-blind operators, so the label is always present.
 */
export function StatusBadge({ kind, label, live = false, className }: StatusBadgeProps) {
  const style = STATUS_STYLES[kind]
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1.5 rounded-md border border-base-700/80 bg-base-900/60 px-2 py-1 text-2xs font-medium',
        style.text,
        className,
      )}
    >
      <span className="relative flex h-1.5 w-1.5" aria-hidden="true">
        {live && (
          <span
            className={clsx('absolute inline-flex h-full w-full animate-ping rounded-full opacity-60', style.dot)}
          />
        )}
        <span className={clsx('relative inline-flex h-1.5 w-1.5 rounded-full', style.dot)} />
      </span>
      {label}
    </span>
  )
}

export function Pill({ children, className, title }: BadgeProps) {
  return (
    <BaseBadge
      title={title}
      className={clsx('bg-base-800 text-ink-muted ring-1 ring-inset ring-base-700', className)}
    >
      {children}
    </BaseBadge>
  )
}
