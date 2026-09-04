import clsx from 'clsx'
import { AlertTriangle } from 'lucide-react'
import { memo } from 'react'
import { Pill } from '@/components/ui/Badge'
import { attackLabel, formatClock, formatPayload, humanizeSignal, severityTone } from '@/utils/format'
import type { CanMessage } from '@/types/api'

/** Render the decoded signals as a compact, readable summary. */
function decodedSummary(decoded: CanMessage['decoded']): string {
  const entries = Object.entries(decoded).filter(
    ([key, value]) => value !== null && value !== undefined && key !== 'counter' && key !== 'checksum_valid',
  )
  if (entries.length === 0) return ''
  return entries
    .slice(0, 3)
    .map(([key, value]) => `${humanizeSignal(key)}: ${typeof value === 'number' ? Number(value.toFixed(2)) : value}`)
    .join(' · ')
}

interface RowProps {
  message: CanMessage
  /** Highlight rows that arrived after the view was opened. */
  isNew?: boolean
}

function Row({ message, isNew = false }: RowProps) {
  const flagged = message.flagged
  const tone = severityTone(message.severity ?? 'INFO')
  const summary = decodedSummary(message.decoded)

  return (
    <tr
      className={clsx(
        flagged && 'bg-red-500/[0.07]',
        flagged && isNew && 'animate-row-flash',
        'transition-colors',
      )}
    >
      <td className="mono whitespace-nowrap text-ink-muted">{formatClock(message.timestamp)}</td>
      <td className="mono whitespace-nowrap font-semibold text-ink">
        <span className="inline-flex items-center gap-1.5">
          {flagged && (
            <AlertTriangle
              className={clsx('h-3 w-3 shrink-0', tone.text)}
              aria-label="Flagged by a detector"
            />
          )}
          {message.can_id_hex}
        </span>
      </td>
      <td className="whitespace-nowrap text-ink-muted">{message.label ?? '—'}</td>
      <td className="mono text-center text-ink-muted">{message.dlc}</td>
      <td className="mono whitespace-nowrap text-ink">{formatPayload(message.data)}</td>
      <td className="max-w-[22rem] truncate text-ink-muted" title={summary || undefined}>
        {summary || '—'}
      </td>
      <td className="whitespace-nowrap">
        <Pill
          className={clsx(
            message.source === 'INJECTED' && 'bg-orange-500/15 text-orange-300 ring-orange-500/40',
          )}
        >
          {message.source}
        </Pill>
      </td>
      <td className="whitespace-nowrap">
        {flagged ? (
          <span className={clsx('text-2xs font-semibold uppercase tracking-wide', tone.text)}>
            {message.attack_types.length > 0
              ? message.attack_types.map(attackLabel).join(', ')
              : (message.threat_level ?? 'Flagged')}
          </span>
        ) : (
          <span className="text-2xs text-ink-faint">Normal</span>
        )}
      </td>
    </tr>
  )
}

/**
 * Memoised: the live table re-renders several times a second and only a
 * handful of rows actually change between flushes.
 */
export const CanMessageRow = memo(Row, (previous, next) => {
  return (
    previous.message.timestamp === next.message.timestamp &&
    previous.message.can_id === next.message.can_id &&
    previous.message.data === next.message.data &&
    previous.message.flagged === next.message.flagged &&
    previous.isNew === next.isNew
  )
})
