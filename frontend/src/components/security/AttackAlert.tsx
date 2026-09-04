import clsx from 'clsx'
import { ChevronDown, ShieldAlert } from 'lucide-react'
import { useState } from 'react'
import { SeverityBadge } from '@/components/ui/Badge'
import { attackLabel, formatClock, formatPercent, humanizeSignal, severityTone } from '@/utils/format'
import type { SecurityEvent } from '@/types/api'

/** Present one evidence value the way an analyst would want to read it. */
function renderEvidenceValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(2)
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  if (Array.isArray(value)) return value.map((item) => renderEvidenceValue(item)).join(', ')
  if (typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, nested]) => `${key}=${renderEvidenceValue(nested)}`)
      .join(' ')
  }
  return String(value)
}

interface AttackAlertProps {
  event: SecurityEvent
  /** Start with the evidence panel open. */
  defaultExpanded?: boolean
  compact?: boolean
}

/**
 * A single security event with its evidence.
 *
 * The evidence block is what separates an alert from an accusation: it shows
 * the observed value, the threshold it crossed, and which rule fired.
 */
export function AttackAlert({ event, defaultExpanded = false, compact = false }: AttackAlertProps) {
  const [expanded, setExpanded] = useState(defaultExpanded)
  const tone = severityTone(event.severity)
  const evidence = Object.entries(event.evidence ?? {}).filter(([key]) => key !== 'attack_type')

  return (
    <article
      className={clsx(
        'rounded-lg border bg-base-900/50 transition',
        event.severity === 'CRITICAL'
          ? 'border-red-500/45'
          : event.severity === 'HIGH'
            ? 'border-orange-500/35'
            : 'border-base-700',
      )}
    >
      <div className={clsx('flex items-start gap-3', compact ? 'p-2.5' : 'p-3')}>
        <span
          className={clsx('mt-0.5 shrink-0 rounded-md bg-base-800 p-1.5', tone.text)}
          aria-hidden="true"
        >
          <ShieldAlert className="h-3.5 w-3.5" />
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold text-ink">{attackLabel(event.attack_type)}</span>
            <SeverityBadge severity={event.severity} />
            {event.can_id_hex && (
              <span className="mono text-2xs text-ink-muted">{event.can_id_hex}</span>
            )}
            <span className="mono text-2xs text-ink-faint">{formatClock(event.timestamp)}</span>
            {event.status !== 'NEW' && (
              <span className="text-2xs uppercase tracking-wide text-ink-faint">{event.status}</span>
            )}
          </div>

          <p className="mt-1 text-xs leading-relaxed text-ink-muted">{event.description}</p>

          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs text-ink-faint">
            <span>
              Confidence <span className="mono text-ink-muted">{formatPercent(event.confidence)}</span>
            </span>
            <span>
              Detector <span className="mono text-ink-muted">{event.detector}</span>
            </span>
            {evidence.length > 0 && (
              <button
                type="button"
                onClick={() => setExpanded((value) => !value)}
                aria-expanded={expanded}
                className="inline-flex items-center gap-1 rounded text-2xs font-medium text-sky-300 hover:text-sky-200 focus:outline-none focus-visible:ring-1 focus-visible:ring-accent"
              >
                {expanded ? 'Hide' : 'Show'} evidence
                <ChevronDown
                  className={clsx('h-3 w-3 transition-transform', expanded && 'rotate-180')}
                  aria-hidden="true"
                />
              </button>
            )}
          </div>

          {expanded && evidence.length > 0 && (
            <dl className="mt-2.5 grid grid-cols-1 gap-x-4 gap-y-1 rounded-md border border-base-700/70 bg-base-950/50 p-2.5 sm:grid-cols-2">
              {evidence.map(([key, value]) => (
                <div key={key} className="flex items-baseline justify-between gap-3">
                  <dt className="truncate text-2xs text-ink-faint">{humanizeSignal(key)}</dt>
                  <dd className="mono shrink-0 text-2xs text-ink">{renderEvidenceValue(value)}</dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      </div>
    </article>
  )
}
