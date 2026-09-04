import { BarChart3, Clock, Hash, TrendingUp } from 'lucide-react'
import { useState } from 'react'
import {
  AttackDistributionChart,
  AttackTimelineChart,
  SeverityChart,
  TopCanIdsChart,
} from '@/components/charts/DistributionCharts'
import { TrafficChart } from '@/components/charts/TrafficChart'
import { Pill } from '@/components/ui/Badge'
import { Field, Select } from '@/components/ui/Controls'
import { Panel } from '@/components/ui/Panel'
import { StatCard } from '@/components/ui/StatCard'
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/States'
import { usePolledResource } from '@/hooks/usePolledResource'
import { useRateSeries } from '@/hooks/useRateSeries'
import { api } from '@/services/api'
import { detectorLabel, formatCompact, formatRate } from '@/utils/format'

const WINDOWS = [
  { label: 'Last 5 minutes', seconds: 300, bucket: 15 },
  { label: 'Last 15 minutes', seconds: 900, bucket: 30 },
  { label: 'Last hour', seconds: 3600, bucket: 60 },
  { label: 'Last 24 hours', seconds: 86_400, bucket: 900 },
  { label: 'All time', seconds: 0, bucket: 300 },
] as const

export function AnalyticsPage() {
  const [windowIndex, setWindowIndex] = useState(1)
  const window = WINDOWS[windowIndex]

  const { series, floodThreshold, suspiciousThreshold } = useRateSeries(180)

  const attackStats = usePolledResource(
    () =>
      api.attackStatistics({
        since_seconds: window.seconds || undefined,
        bucket_seconds: window.bucket,
        buckets: 80,
      }),
    [windowIndex],
    { intervalMs: 10_000 },
  )

  const trafficStats = usePolledResource(
    () => api.trafficStatistics(window.seconds || undefined),
    [windowIndex],
    { intervalMs: 10_000 },
  )

  const stats = attackStats.data
  const traffic = trafficStats.data
  const loading = attackStats.loading || trafficStats.loading
  const error = attackStats.error ?? trafficStats.error

  const retry = () => {
    void attackStats.refetch()
    void trafficStats.refetch()
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold tracking-tight text-ink">Analytics</h2>
          <p className="text-xs text-ink-muted">
            Traffic and attack behaviour over the selected window, from the stored history.
          </p>
        </div>
        <Field label="Time window" className="w-52">
          {(id) => (
            <Select
              id={id}
              value={String(windowIndex)}
              onChange={(event) => setWindowIndex(Number(event.target.value))}
            >
              {WINDOWS.map((option, index) => (
                <option key={option.label} value={index}>
                  {option.label}
                </option>
              ))}
            </Select>
          )}
        </Field>
      </div>

      {error && !stats && !traffic ? (
        <Panel>
          <ErrorState error={error} onRetry={retry} />
        </Panel>
      ) : (
        <>
          <section aria-label="Analytics summary" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard
              label="Events in window"
              value={formatCompact(stats?.total_events ?? 0)}
              icon={<BarChart3 className="h-4 w-4" />}
              tone={(stats?.total_events ?? 0) > 0 ? 'warn' : 'neutral'}
              hint={`${stats?.events_last_hour ?? 0} in the last hour`}
            />
            <StatCard
              label="Stored frames"
              value={formatCompact(traffic?.stored_messages ?? 0)}
              icon={<Hash className="h-4 w-4" />}
              hint={`${traffic?.unique_can_ids ?? 0} distinct identifiers seen live`}
            />
            <StatCard
              label="Peak bus load"
              value={formatRate(traffic?.peak_rate_msg_per_s)}
              unit="msg/s"
              icon={<TrendingUp className="h-4 w-4" />}
              tone="accent"
              hint={`Average ${formatRate(traffic?.average_rate_msg_per_s)} msg/s`}
            />
            <StatCard
              label="Flagged frames"
              value={formatCompact(traffic?.flagged_messages ?? 0)}
              icon={<Clock className="h-4 w-4" />}
              tone={(traffic?.flagged_messages ?? 0) > 0 ? 'warn' : 'neutral'}
              hint={`${traffic?.invalid_messages ?? 0} rejected as invalid`}
            />
          </section>

          <Panel
            title="Bus load history"
            subtitle="Live rate with the detector's flood thresholds"
            icon={<TrendingUp className="h-4 w-4" />}
          >
            <TrafficChart
              data={series}
              floodThreshold={floodThreshold}
              suspiciousThreshold={suspiciousThreshold}
              height={260}
            />
          </Panel>

          <div className="grid gap-4 xl:grid-cols-2">
            <Panel
              title="Attack frequency"
              subtitle={`Events per ${stats?.bucket_seconds ?? window.bucket}s window, stacked by severity`}
            >
              {loading && !stats ? (
                <LoadingState />
              ) : (
                <AttackTimelineChart
                  buckets={stats?.timeline ?? []}
                  bucketSeconds={stats?.bucket_seconds ?? window.bucket}
                />
              )}
            </Panel>

            <Panel title="Attack distribution" subtitle="Share of events by attack type">
              {loading && !stats ? <LoadingState /> : <AttackDistributionChart counts={stats?.by_attack_type ?? {}} />}
            </Panel>
          </div>

          <div className="grid gap-4 xl:grid-cols-2">
            <Panel title="Severity distribution" subtitle="How serious the detections were">
              {loading && !stats ? <LoadingState /> : <SeverityChart counts={stats?.by_severity ?? {}} />}
            </Panel>

            <Panel
              title="Busiest identifiers"
              subtitle="Frame counts from the live window; the red segment is flagged traffic"
            >
              {loading && !traffic ? <LoadingState /> : <TopCanIdsChart items={traffic?.top_can_ids ?? []} />}
            </Panel>
          </div>

          <div className="grid gap-4 xl:grid-cols-2">
            <Panel title="Suspicious identifiers" subtitle="Identifiers that generated security events">
              {stats?.top_can_ids?.length ? (
                <table className="data-table">
                  <caption className="sr-only">Identifiers ranked by number of security events</caption>
                  <thead>
                    <tr>
                      <th scope="col">CAN ID</th>
                      <th scope="col">Label</th>
                      <th scope="col" className="text-right">
                        Events
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {stats.top_can_ids.map((item) => (
                      <tr key={item.can_id}>
                        <td className="mono font-semibold text-ink">{item.can_id_hex}</td>
                        <td className="text-ink-muted">{item.label ?? '—'}</td>
                        <td className="mono text-right text-amber-300">{item.count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <EmptyState
                  title="No suspicious identifiers"
                  description="No identifier has generated a security event in this window."
                />
              )}
            </Panel>

            <Panel title="Detector activity" subtitle="Which detector raised each event">
              {stats && Object.keys(stats.by_detector).length > 0 ? (
                <ul className="space-y-2">
                  {Object.entries(stats.by_detector)
                    .sort((a, b) => b[1] - a[1])
                    .map(([detector, count]) => {
                      const max = Math.max(...Object.values(stats.by_detector))
                      return (
                        <li key={detector}>
                          <div className="flex items-center justify-between text-xs">
                            <span className="text-ink">{detectorLabel(detector)}</span>
                            <span className="mono text-ink-muted">{count}</span>
                          </div>
                          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-base-800">
                            <div
                              className="h-full rounded-full bg-accent/70"
                              style={{ width: `${max > 0 ? (count / max) * 100 : 0}%` }}
                            />
                          </div>
                        </li>
                      )
                    })}
                </ul>
              ) : (
                <EmptyState title="No detector activity" description="Detectors report here once they fire." />
              )}
            </Panel>
          </div>

          <Panel title="Stored traffic by identifier" subtitle="Counts from the database, not the live buffer">
            {traffic?.messages_by_can_id?.length ? (
              <div className="flex flex-wrap gap-2">
                {traffic.messages_by_can_id.map((item) => (
                  <Pill key={item.can_id} title={`${item.count.toLocaleString()} frames stored`}>
                    <span className="mono">{item.can_id_hex}</span>
                    <span className="ml-1 text-ink-faint">{formatCompact(item.count)}</span>
                  </Pill>
                ))}
              </div>
            ) : (
              <EmptyState
                title="Nothing stored yet"
                description="Persisted counts appear once the writer commits its first batch."
              />
            )}
          </Panel>
        </>
      )}
    </div>
  )
}
