import {
  Activity,
  Cpu,
  Gauge,
  Radio,
  ShieldAlert,
  ShieldCheck,
  Siren,
} from 'lucide-react'
import { useMemo, useRef } from 'react'
import { Link } from 'react-router-dom'
import { AttackDistributionChart } from '@/components/charts/DistributionCharts'
import { TrafficChart } from '@/components/charts/TrafficChart'
import { AttackAlert } from '@/components/security/AttackAlert'
import { TrafficTable } from '@/components/traffic/TrafficTable'
import { Pill, StatusBadge } from '@/components/ui/Badge'
import { Panel } from '@/components/ui/Panel'
import { StatCard, type StatTone } from '@/components/ui/StatCard'
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/States'
import { useLiveStatus, useLiveTraffic } from '@/hooks/liveData'
import { usePolledResource } from '@/hooks/usePolledResource'
import { useRateSeries } from '@/hooks/useRateSeries'
import { api } from '@/services/api'
import { detectorLabel, formatCompact, formatDuration, formatRate } from '@/utils/format'

const THREAT_TONE: Record<string, StatTone> = {
  NORMAL: 'ok',
  SUSPICIOUS: 'warn',
  ATTACK: 'bad',
}

export function DashboardPage() {
  const { systemStatus, monitorStatus, simulationStatus, alerts, threatLevel, currentRate, activeAlerts, attacksTotal } =
    useLiveStatus()
  const { messages } = useLiveTraffic()
  const { series, floodThreshold, suspiciousThreshold } = useRateSeries(120)

  const summary = usePolledResource(() => api.securitySummary(8), [], { intervalMs: 5_000 })

  // Frames that arrived after the page opened get the "new" highlight.
  const openedAt = useRef(Date.now() / 1000)

  const monitoring = monitorStatus?.running ?? false
  const traffic = systemStatus?.traffic
  const totalMessages = traffic?.total_messages ?? 0

  const recentAlerts = useMemo(() => {
    // Prefer the live stream; fall back to stored events right after a reload.
    if (alerts.length > 0) return alerts.slice(0, 6)
    return summary.data?.recent_events.slice(0, 6) ?? []
  }, [alerts, summary.data])

  const attackCounts = summary.data?.by_attack_type ?? systemStatus?.security.by_attack_type ?? {}

  return (
    <div className="space-y-4">
      {/* ---- Headline metrics -------------------------------------------- */}
      <section aria-label="System overview" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <StatCard
          label="System status"
          value={monitoring ? 'ONLINE' : 'IDLE'}
          hint={
            monitoring
              ? `Uptime ${formatDuration(monitorStatus?.uptime_seconds)}`
              : 'Start the monitor to begin'
          }
          icon={monitoring ? <ShieldCheck className="h-4 w-4" /> : <Cpu className="h-4 w-4" />}
          tone={monitoring ? 'ok' : 'neutral'}
        />
        <StatCard
          label="Messages / sec"
          value={formatRate(currentRate)}
          unit="msg/s"
          hint={`Peak ${formatRate(traffic?.peak_rate_msg_per_s)} · ${traffic?.unique_can_ids ?? 0} IDs`}
          icon={<Radio className="h-4 w-4" />}
          tone="accent"
        />
        <StatCard
          label="Total messages"
          value={formatCompact(totalMessages)}
          hint={`${formatCompact(traffic?.flagged_messages ?? 0)} flagged by a detector`}
          icon={<Gauge className="h-4 w-4" />}
        />
        <StatCard
          label="Attacks detected"
          value={formatCompact(attacksTotal)}
          hint={`${summary.data?.events_stored ?? 0} stored · ${summary.data?.events_last_hour ?? 0} in the last hour`}
          icon={<ShieldAlert className="h-4 w-4" />}
          tone={attacksTotal > 0 ? 'warn' : 'neutral'}
        />
        <StatCard
          label="Active alerts"
          value={formatCompact(activeAlerts)}
          hint={`Threat level: ${threatLevel}`}
          icon={<Siren className="h-4 w-4" />}
          tone={THREAT_TONE[threatLevel] ?? 'neutral'}
          pulse={threatLevel === 'ATTACK' && activeAlerts > 0}
        />
      </section>

      {/* ---- Traffic and distribution ------------------------------------ */}
      <div className="grid gap-4 xl:grid-cols-3">
        <Panel
          className="xl:col-span-2"
          title="Bus load"
          subtitle="Messages per second with the configured flood thresholds"
          icon={<Activity className="h-4 w-4" />}
          actions={
            <>
              <Pill>{simulationStatus?.mode ?? 'IDLE'}</Pill>
              <StatusBadge
                kind={simulationStatus?.running ? 'busy' : 'idle'}
                label={simulationStatus?.running ? 'Generating' : 'Simulator off'}
                live={simulationStatus?.running}
              />
            </>
          }
        >
          <TrafficChart
            data={series}
            floodThreshold={floodThreshold}
            suspiciousThreshold={suspiciousThreshold}
            height={252}
          />
        </Panel>

        <Panel
          title="Attack distribution"
          subtitle="Security events by type"
          icon={<ShieldAlert className="h-4 w-4" />}
        >
          <AttackDistributionChart counts={attackCounts} height={252} />
        </Panel>
      </div>

      {/* ---- Events and live traffic -------------------------------------- */}
      <div className="grid gap-4 xl:grid-cols-2">
        <Panel
          title="Recent security events"
          subtitle="Newest first, with the evidence behind each verdict"
          icon={<Siren className="h-4 w-4" />}
          actions={
            <Link
              to="/security"
              className="rounded text-2xs font-medium text-sky-300 hover:text-sky-200 focus:outline-none focus-visible:ring-1 focus-visible:ring-accent"
            >
              View all →
            </Link>
          }
        >
          {summary.loading && recentAlerts.length === 0 ? (
            <LoadingState label="Loading security events…" />
          ) : summary.error && recentAlerts.length === 0 ? (
            <ErrorState error={summary.error} onRetry={summary.refetch} />
          ) : recentAlerts.length === 0 ? (
            <EmptyState
              icon={<ShieldCheck className="h-5 w-5" />}
              title="No attacks detected"
              description="The bus is clean. Trigger an attack from the Simulator page to see detection in action."
              action={
                <Link
                  to="/simulator"
                  className="inline-flex items-center rounded-md border border-accent/50 bg-accent/15 px-3 py-1.5 text-xs font-medium text-sky-200 transition hover:bg-accent/25"
                >
                  Open the simulator
                </Link>
              }
            />
          ) : (
            <ul className="space-y-2">
              {recentAlerts.map((event, index) => (
                <li key={event.id ?? `${event.timestamp}-${index}`}>
                  <AttackAlert event={event} compact />
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel
          title="Live CAN traffic"
          subtitle={`Newest frames on ${monitorStatus?.interface?.channel ?? 'the bus'}`}
          icon={<Radio className="h-4 w-4" />}
          flush
          actions={
            <Link
              to="/traffic"
              className="rounded text-2xs font-medium text-sky-300 hover:text-sky-200 focus:outline-none focus-visible:ring-1 focus-visible:ring-accent"
            >
              Open trace →
            </Link>
          }
        >
          <TrafficTable
            messages={messages.slice(-14).reverse()}
            highlightAfter={openedAt.current}
            maxHeight="20rem"
            emptyTitle="Waiting for CAN frames"
            emptyDescription="Start the monitor and the simulator to see live bus traffic here."
          />
        </Panel>
      </div>

      {/* ---- Detectors ---------------------------------------------------- */}
      <Panel
        title="Detection engine"
        subtitle="Every detector currently inspecting the frame stream"
        icon={<ShieldCheck className="h-4 w-4" />}
      >
        {summary.data?.detectors?.length ? (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {summary.data.detectors.map((detector) => (
              <div
                key={detector.name}
                className="rounded-lg border border-base-700 bg-base-900/50 p-3"
              >
                <div className="flex items-center justify-between gap-2">
                  <p className="truncate text-xs font-semibold text-ink">
                    {detectorLabel(detector.name)}
                  </p>
                  <StatusBadge
                    kind={detector.enabled ? 'ok' : 'idle'}
                    label={detector.enabled ? 'Active' : 'Off'}
                  />
                </div>
                <p className="mt-1.5 line-clamp-2 text-2xs leading-relaxed text-ink-muted">
                  {detector.description}
                </p>
                <dl className="mt-2 flex items-center justify-between text-2xs">
                  <div>
                    <dt className="text-ink-faint">Inspected</dt>
                    <dd className="mono text-ink">{formatCompact(detector.inspections)}</dd>
                  </div>
                  <div className="text-right">
                    <dt className="text-ink-faint">Detections</dt>
                    <dd
                      className={
                        detector.detections > 0 ? 'mono text-amber-300' : 'mono text-ink-muted'
                      }
                    >
                      {formatCompact(detector.detections)}
                    </dd>
                  </div>
                </dl>
              </div>
            ))}
          </div>
        ) : summary.loading ? (
          <LoadingState label="Loading detectors…" />
        ) : (
          <EmptyState title="Detector status unavailable" description="The backend has not reported detector state yet." />
        )}
      </Panel>
    </div>
  )
}
