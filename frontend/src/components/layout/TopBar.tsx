import { Menu, Radio, RefreshCw, Wifi, WifiOff } from 'lucide-react'
import { useLiveStatus } from '@/hooks/liveData'
import { StatusBadge, ThreatBadge, type StatusKind } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Controls'
import { formatRate } from '@/utils/format'
import type { ConnectionState } from '@/types/api'

const CONNECTION_LABELS: Record<ConnectionState, { kind: StatusKind; label: string; live: boolean }> = {
  connecting: { kind: 'busy', label: 'Connecting', live: true },
  open: { kind: 'ok', label: 'Stream live', live: true },
  reconnecting: { kind: 'warn', label: 'Reconnecting', live: true },
  closed: { kind: 'bad', label: 'Disconnected', live: false },
}

export function TopBar({ onOpenNav }: { onOpenNav: () => void }) {
  const { connection, threatLevel, currentRate, monitorStatus, reconnect, reconnectAttempts } =
    useLiveStatus()
  const stream = CONNECTION_LABELS[connection]
  const monitoring = monitorStatus?.running ?? false

  return (
    <header className="sticky top-0 z-20 border-b border-base-800 bg-base-950/85 backdrop-blur">
      <div className="flex items-center gap-3 px-4 py-3">
        <button
          type="button"
          onClick={onOpenNav}
          className="rounded-md p-1.5 text-ink-muted hover:bg-base-800 hover:text-ink lg:hidden"
          aria-label="Open navigation"
        >
          <Menu className="h-4 w-4" />
        </button>

        <div className="min-w-0 flex-1">
          <h1 className="truncate text-sm font-semibold tracking-tight text-ink">
            Automotive CAN Bus Intrusion Detection
          </h1>
          <p className="truncate text-2xs text-ink-faint">
            {monitoring
              ? `Monitoring ${monitorStatus?.interface?.channel ?? 'bus'} via ${
                  monitorStatus?.interface?.backend ?? 'interface'
                }`
              : 'Monitoring stopped'}
          </p>
        </div>

        <div className="flex items-center gap-2">
          <span className="hidden items-center gap-1.5 rounded-md border border-base-700 bg-base-900/60 px-2 py-1 text-2xs text-ink-muted sm:inline-flex">
            <Radio className="h-3 w-3 text-ink-faint" aria-hidden="true" />
            <span className="mono text-ink">{formatRate(currentRate)}</span>
            <span className="text-ink-faint">msg/s</span>
          </span>

          <StatusBadge
            kind={monitoring ? 'ok' : 'idle'}
            label={monitoring ? 'System online' : 'Monitor idle'}
            live={monitoring}
          />

          <ThreatBadge level={threatLevel} />

          <span className="hidden md:inline-flex">
            <StatusBadge kind={stream.kind} label={stream.label} live={stream.live} />
          </span>

          {connection !== 'open' && (
            <Button
              size="sm"
              variant="secondary"
              onClick={reconnect}
              icon={<RefreshCw className="h-3 w-3" />}
              title={
                reconnectAttempts > 0
                  ? `${reconnectAttempts} reconnect attempt(s) so far`
                  : 'Reconnect the live stream'
              }
            >
              Reconnect
            </Button>
          )}
        </div>
      </div>

      {connection !== 'open' && (
        <div
          role="status"
          className="flex items-center gap-2 border-t border-amber-500/25 bg-amber-500/10 px-4 py-1.5 text-2xs text-amber-200"
        >
          {connection === 'closed' ? (
            <WifiOff className="h-3.5 w-3.5" aria-hidden="true" />
          ) : (
            <Wifi className="h-3.5 w-3.5" aria-hidden="true" />
          )}
          <span>
            {connection === 'connecting'
              ? 'Opening the live event stream…'
              : `Live stream interrupted — retrying automatically (attempt ${reconnectAttempts}). Historical data is still available.`}
          </span>
        </div>
      )}
    </header>
  )
}
