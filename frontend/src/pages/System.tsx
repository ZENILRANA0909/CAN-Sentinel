import { Cpu, Database, HardDrive, Play, Radio, Square, Wifi } from 'lucide-react'
import { useCallback, useState } from 'react'
import { Pill, StatusBadge, type StatusKind } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Controls'
import { Panel } from '@/components/ui/Panel'
import { StatCard } from '@/components/ui/StatCard'
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/States'
import { useLiveStatus } from '@/hooks/liveData'
import { usePolledResource } from '@/hooks/usePolledResource'
import { ApiRequestError, api } from '@/services/api'
import {
  detectorLabel,
  formatBytes,
  formatClock,
  formatCompact,
  formatDuration,
} from '@/utils/format'

function DefinitionList({ rows }: { rows: Array<[string, React.ReactNode]> }) {
  return (
    <dl className="space-y-1.5 text-xs">
      {rows.map(([label, value]) => (
        <div key={label} className="flex items-start justify-between gap-3">
          <dt className="text-ink-faint">{label}</dt>
          <dd className="mono max-w-[60%] truncate text-right text-ink" title={String(value ?? '')}>
            {value ?? '—'}
          </dd>
        </div>
      ))}
    </dl>
  )
}

export function SystemPage() {
  const { connection, systemStatus, monitorStatus } = useLiveStatus()

  const health = usePolledResource(() => api.health(), [], { intervalMs: 10_000 })
  const status = usePolledResource(() => api.status(), [], { intervalMs: 5_000 })
  const events = usePolledResource(() => api.systemEvents(25), [], { intervalMs: 10_000 })

  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const live = systemStatus ?? status.data
  const monitor = monitorStatus ?? live?.monitor
  const iface = monitor?.interface

  const control = useCallback(
    async (action: 'start' | 'stop') => {
      setBusy(action)
      setError(null)
      try {
        await (action === 'start' ? api.startMonitor() : api.stopMonitor())
        await Promise.all([status.refetch(), events.refetch()])
      } catch (caught) {
        setError(caught instanceof ApiRequestError ? caught.message : 'The control action failed.')
      } finally {
        setBusy(null)
      }
    },
    [status, events],
  )

  if (status.loading && !live) return <LoadingState label="Loading system status…" />
  if (status.error && !live) return <ErrorState error={status.error} onRetry={status.refetch} />

  const dbCheck = (health.data?.checks?.database ?? {}) as Record<string, unknown>
  const writer = live?.storage?.writer ?? {}
  const healthy = health.data?.status === 'healthy'
  const streamKind: StatusKind =
    connection === 'open' ? 'ok' : connection === 'closed' ? 'bad' : 'warn'

  return (
    <div className="space-y-4">
      <section aria-label="System health" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Backend"
          value={healthy ? 'HEALTHY' : health.data ? 'DEGRADED' : 'UNKNOWN'}
          tone={healthy ? 'ok' : 'bad'}
          icon={<Cpu className="h-4 w-4" />}
          hint={`v${live?.version ?? '—'} · ${live?.environment ?? '—'}`}
        />
        <StatCard
          label="Uptime"
          value={formatDuration(live?.uptime_seconds)}
          hint={`Started ${formatClock(live?.started_at)}`}
        />
        <StatCard
          label="CAN interface"
          value={iface?.is_open ? 'OPEN' : 'CLOSED'}
          tone={iface?.is_open ? 'ok' : 'neutral'}
          icon={<Radio className="h-4 w-4" />}
          hint={iface ? `${iface.backend} · ${iface.channel}` : 'No interface'}
        />
        <StatCard
          label="WebSocket clients"
          value={formatCompact(live?.websocket?.clients ?? 0)}
          icon={<Wifi className="h-4 w-4" />}
          tone={connection === 'open' ? 'ok' : 'warn'}
          hint={`Stream ${connection}`}
        />
      </section>

      {error && (
        <p role="alert" className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-200">
          {error}
        </p>
      )}

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel
          title="Monitoring service"
          subtitle="Receive loop and CAN interface"
          icon={<Radio className="h-4 w-4" />}
          actions={
            <>
              <StatusBadge
                kind={monitor?.running ? 'ok' : 'idle'}
                label={monitor?.running ? 'Running' : 'Stopped'}
                live={monitor?.running}
              />
              <Button
                size="sm"
                variant={monitor?.running ? 'danger' : 'primary'}
                loading={busy !== null}
                icon={
                  monitor?.running ? <Square className="h-3 w-3" /> : <Play className="h-3 w-3" />
                }
                onClick={() => control(monitor?.running ? 'stop' : 'start')}
              >
                {monitor?.running ? 'Stop' : 'Start'}
              </Button>
            </>
          }
        >
          <DefinitionList
            rows={[
              ['State', monitor?.running ? 'Running' : 'Stopped'],
              ['Uptime', formatDuration(monitor?.uptime_seconds)],
              ['Batches processed', formatCompact(monitor?.batches_processed ?? 0)],
              ['Batch size', monitor?.batch_size ?? '—'],
              ['Errors', monitor?.errors ?? 0],
              ['Last error', monitor?.last_error ?? 'none'],
            ]}
          />
          <hr className="my-3 border-base-700/70" />
          {iface ? (
            <DefinitionList
              rows={[
                ['Backend', iface.backend],
                ['Channel', iface.channel],
                ['Bitrate', `${(iface.bitrate / 1000).toFixed(0)} kbit/s`],
                ['Queue', `${iface.queue_pending} / ${iface.queue_size}`],
                ['Frames received', formatCompact(iface.statistics.received)],
                ['Frames transmitted', formatCompact(iface.statistics.sent)],
                [
                  'Dropped (queue full)',
                  <span
                    key="dropped"
                    className={iface.statistics.dropped > 0 ? 'text-amber-300' : undefined}
                  >
                    {formatCompact(iface.statistics.dropped)}
                  </span>,
                ],
              ]}
            />
          ) : (
            <EmptyState title="No CAN interface open" description="Start the monitor to open the bus." />
          )}
        </Panel>

        <Panel title="Storage" subtitle="Database and the batching writer" icon={<Database className="h-4 w-4" />}>
          <DefinitionList
            rows={[
              [
                'Database',
                <StatusBadge
                  key="db"
                  kind={dbCheck.healthy ? 'ok' : 'bad'}
                  label={dbCheck.healthy ? 'Healthy' : 'Unavailable'}
                />,
              ],
              ['Engine URL', String(dbCheck.url ?? '—')],
              ['File size', dbCheck.size_bytes ? formatBytes(Number(dbCheck.size_bytes)) : '—'],
              ['Rows written (messages)', formatCompact(Number(writer.messages_written ?? 0))],
              ['Rows written (events)', formatCompact(Number(writer.security_events_written ?? 0))],
              [
                'Dropped (queue full)',
                <span
                  key="wdrop"
                  className={Number(writer.messages_dropped ?? 0) > 0 ? 'text-amber-300' : undefined}
                >
                  {formatCompact(Number(writer.messages_dropped ?? 0))}
                </span>,
              ],
              ['Queued now', formatCompact(Number(writer.queued_messages ?? 0))],
              ['Write errors', Number(writer.errors ?? 0)],
            ]}
          />
          <hr className="my-3 border-base-700/70" />
          <p className="mb-2 text-2xs font-medium uppercase tracking-wide text-ink-faint">Retention</p>
          <DefinitionList
            rows={Object.entries(
              (live?.storage?.retention?.limits as Record<string, number>) ?? {},
            ).map(([key, value]) => [key.replace(/_/g, ' '), formatCompact(value)])}
          />
        </Panel>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title="Detection engine" subtitle="Per-detector counters and internal state">
          {live?.detection?.detectors?.length ? (
            <div className="space-y-3">
              <div className="flex flex-wrap gap-2">
                <Pill>Analysed {formatCompact(live.detection.analysed_messages)}</Pill>
                <Pill>Emitted {formatCompact(live.detection.events_emitted)}</Pill>
                <Pill title="Repeat detections collapsed by the cooldown">
                  Suppressed {formatCompact(live.detection.events_suppressed)}
                </Pill>
              </div>
              {live.detection.detectors.map((detector) => (
                <div key={detector.name} className="rounded-lg border border-base-700 bg-base-900/50 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-xs font-semibold text-ink">{detectorLabel(detector.name)}</p>
                    <StatusBadge kind={detector.enabled ? 'ok' : 'idle'} label={detector.enabled ? 'Active' : 'Off'} />
                  </div>
                  <p className="mt-1 text-2xs text-ink-muted">{detector.description}</p>
                  <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3">
                    {Object.entries(detector.state).map(([key, value]) => (
                      <div key={key} className="flex items-baseline justify-between gap-2 text-2xs">
                        <span className="truncate text-ink-faint">{key.replace(/_/g, ' ')}</span>
                        <span className="mono shrink-0 text-ink">
                          {Array.isArray(value) ? value.join(', ') || '—' : String(value ?? '—')}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <LoadingState />
          )}
        </Panel>

        <Panel
          title="System audit trail"
          subtitle="Lifecycle transitions and recorded errors"
          icon={<HardDrive className="h-4 w-4" />}
          flush
        >
          {events.loading && !events.data ? (
            <LoadingState />
          ) : events.error && !events.data ? (
            <ErrorState error={events.error} onRetry={events.refetch} />
          ) : events.data && events.data.length > 0 ? (
            <div className="max-h-[26rem] overflow-auto">
              <table className="data-table">
                <caption className="sr-only">System events, newest first</caption>
                <thead>
                  <tr>
                    <th scope="col">Time</th>
                    <th scope="col">Event</th>
                    <th scope="col">Message</th>
                  </tr>
                </thead>
                <tbody>
                  {events.data.map((event) => (
                    <tr key={event.id ?? event.timestamp}>
                      <td className="mono whitespace-nowrap text-ink-muted">
                        {formatClock(event.timestamp)}
                      </td>
                      <td className="whitespace-nowrap">
                        <Pill
                          className={
                            event.severity === 'HIGH' || event.severity === 'CRITICAL'
                              ? 'bg-red-500/15 text-red-300 ring-red-500/40'
                              : undefined
                          }
                        >
                          {event.event_type}
                        </Pill>
                      </td>
                      <td className="text-ink-muted">{event.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState title="No system events" description="Lifecycle events appear here as they happen." />
          )}
        </Panel>
      </div>

      <Panel title="Live stream" subtitle="WebSocket fan-out to connected dashboards" icon={<Wifi className="h-4 w-4" />}>
        <div className="grid gap-4 sm:grid-cols-2">
          <DefinitionList
            rows={[
              ['This client', <StatusBadge key="c" kind={streamKind} label={connection} />],
              ['Connected clients', live?.websocket?.clients ?? 0],
              ['Client capacity', live?.websocket?.max_clients ?? '—'],
              ['Events published', formatCompact(live?.websocket?.events_published ?? 0)],
            ]}
          />
          <DefinitionList
            rows={[
              ['Flush interval', `${live?.websocket?.flush_interval_ms ?? '—'} ms`],
              ['Frames per flush', live?.websocket?.max_messages_per_flush ?? '—'],
              ['Buffered now', live?.websocket?.buffered_messages ?? 0],
              ['Config revision', live?.config_revision ?? '—'],
            ]}
          />
        </div>
      </Panel>
    </div>
  )
}
