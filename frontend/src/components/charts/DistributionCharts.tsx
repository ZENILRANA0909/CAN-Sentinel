import {
  Bar,
  BarChart,
  Cell,
  CartesianGrid,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { ChartDescription, TooltipCard } from './ChartPrimitives'
import { AXIS_PROPS, CHART, GRID_PROPS } from './chartTheme'
import { EmptyState } from '@/components/ui/States'
import {
  SEVERITY_ORDER,
  attackColor,
  attackLabel,
  formatClock,
  severityTone,
} from '@/utils/format'
import type { Severity, TimelineBucket, TopCanId } from '@/types/api'

/* ---------------------------------------------------------------------- */
/* Attack type distribution                                                */
/* ---------------------------------------------------------------------- */

export function AttackDistributionChart({
  counts,
  height = 220,
}: {
  counts: Record<string, number>
  height?: number
}) {
  const data = Object.entries(counts)
    .filter(([type, value]) => value > 0 && type !== 'NONE')
    .map(([type, value]) => ({ type, label: attackLabel(type), value, color: attackColor(type) }))

  if (data.length === 0) {
    return (
      <EmptyState
        title="No attacks detected"
        description="The distribution appears once the detection engine records its first event."
      />
    )
  }

  const total = data.reduce((sum, entry) => sum + entry.value, 0)

  return (
    <>
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data}
              dataKey="value"
              nameKey="label"
              innerRadius="52%"
              outerRadius="80%"
              paddingAngle={2}
              stroke="#0a0f18"
              strokeWidth={2}
              isAnimationActive={false}
            >
              {data.map((entry) => (
                <Cell key={entry.type} fill={entry.color} />
              ))}
            </Pie>
            <Tooltip
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null
                const entry = payload[0].payload as (typeof data)[number]
                return (
                  <TooltipCard
                    title={entry.label}
                    rows={[
                      { label: 'Events', value: entry.value, color: entry.color },
                      {
                        label: 'Share',
                        value: `${((entry.value / total) * 100).toFixed(1)}%`,
                      },
                    ]}
                  />
                )
              }}
            />
            <Legend
              verticalAlign="bottom"
              height={28}
              formatter={(value) => <span className="text-2xs text-ink-muted">{value}</span>}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>
      <ChartDescription
        caption="Security events by attack type"
        headers={['Attack type', 'Events']}
        rows={data.map((entry) => [entry.label, entry.value])}
      />
    </>
  )
}

/* ---------------------------------------------------------------------- */
/* Severity distribution                                                   */
/* ---------------------------------------------------------------------- */

export function SeverityChart({
  counts,
  height = 220,
}: {
  counts: Record<string, number>
  height?: number
}) {
  const data = SEVERITY_ORDER.map((severity) => ({
    severity,
    label: severityTone(severity).label,
    value: counts[severity] ?? 0,
    color: severityTone(severity).hex,
  }))

  if (data.every((entry) => entry.value === 0)) {
    return <EmptyState title="No events recorded" description="Severity breakdown appears with the first alert." />
  }

  return (
    <>
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
            <CartesianGrid {...GRID_PROPS} />
            <XAxis dataKey="label" {...AXIS_PROPS} />
            <YAxis {...AXIS_PROPS} width={40} allowDecimals={false} />
            <Tooltip
              cursor={{ fill: 'rgba(255,255,255,0.04)' }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null
                const entry = payload[0].payload as (typeof data)[number]
                return (
                  <TooltipCard
                    title={`${entry.label} severity`}
                    rows={[{ label: 'Events', value: entry.value, color: entry.color }]}
                  />
                )
              }}
            />
            <Bar dataKey="value" radius={[3, 3, 0, 0]} isAnimationActive={false}>
              {data.map((entry) => (
                <Cell key={entry.severity} fill={entry.color} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <ChartDescription
        caption="Security events by severity"
        headers={['Severity', 'Events']}
        rows={data.map((entry) => [entry.label, entry.value])}
      />
    </>
  )
}

/* ---------------------------------------------------------------------- */
/* Busiest identifiers                                                     */
/* ---------------------------------------------------------------------- */

export function TopCanIdsChart({ items, height = 260 }: { items: TopCanId[]; height?: number }) {
  if (items.length === 0) {
    return <EmptyState title="No traffic recorded" description="Identifier activity appears once frames arrive." />
  }

  const data = items.slice(0, 10).map((item) => ({
    ...item,
    name: item.can_id_hex,
    clean: Math.max(item.count - item.flagged, 0),
  }))

  return (
    <>
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, bottom: 4, left: 8 }}>
            <CartesianGrid {...GRID_PROPS} horizontal={false} vertical />
            <XAxis type="number" {...AXIS_PROPS} allowDecimals={false} />
            <YAxis type="category" dataKey="name" {...AXIS_PROPS} width={62} />
            <Tooltip
              cursor={{ fill: 'rgba(255,255,255,0.04)' }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null
                const entry = payload[0].payload as (typeof data)[number]
                return (
                  <TooltipCard
                    title={`${entry.can_id_hex} — ${entry.label ?? 'Unknown'}`}
                    rows={[
                      { label: 'Frames', value: entry.count.toLocaleString(), color: CHART.accent },
                      { label: 'Flagged', value: entry.flagged.toLocaleString(), color: CHART.danger },
                    ]}
                  />
                )
              }}
            />
            <Bar dataKey="clean" stackId="a" fill={CHART.accent} fillOpacity={0.75} isAnimationActive={false} />
            <Bar
              dataKey="flagged"
              stackId="a"
              fill={CHART.danger}
              radius={[0, 3, 3, 0]}
              isAnimationActive={false}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <ChartDescription
        caption="Busiest CAN identifiers"
        headers={['Identifier', 'Frames', 'Flagged']}
        rows={data.map((entry) => [entry.can_id_hex, entry.count, entry.flagged])}
      />
    </>
  )
}

/* ---------------------------------------------------------------------- */
/* Attack timeline                                                         */
/* ---------------------------------------------------------------------- */

export function AttackTimelineChart({
  buckets,
  bucketSeconds,
  height = 240,
}: {
  buckets: TimelineBucket[]
  bucketSeconds: number
  height?: number
}) {
  if (buckets.length === 0) {
    return (
      <EmptyState
        title="No attack history"
        description="Run an attack simulation to populate the timeline."
      />
    )
  }

  const present = SEVERITY_ORDER.filter((severity) =>
    buckets.some((bucket) => Number(bucket[severity] ?? 0) > 0),
  )

  return (
    <>
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={buckets} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
            <CartesianGrid {...GRID_PROPS} />
            <XAxis
              dataKey="bucket_start"
              {...AXIS_PROPS}
              minTickGap={40}
              tickFormatter={(value: number) => formatClock(value).slice(0, 5)}
            />
            <YAxis {...AXIS_PROPS} width={40} allowDecimals={false} />
            <Tooltip
              cursor={{ fill: 'rgba(255,255,255,0.04)' }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null
                const bucket = payload[0].payload as TimelineBucket
                return (
                  <TooltipCard
                    title={`${formatClock(bucket.bucket_start).slice(0, 8)} · ${bucketSeconds}s window`}
                    rows={[
                      { label: 'Total', value: bucket.total },
                      ...present.map((severity) => ({
                        label: severityTone(severity).label,
                        value: Number(bucket[severity] ?? 0),
                        color: severityTone(severity).hex,
                      })),
                    ]}
                  />
                )
              }}
            />
            {present.map((severity, index) => (
              <Bar
                key={severity}
                dataKey={severity}
                stackId="severity"
                fill={severityTone(severity as Severity).hex}
                radius={index === present.length - 1 ? [3, 3, 0, 0] : undefined}
                isAnimationActive={false}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
      <ChartDescription
        caption="Security events over time by severity"
        headers={['Window start', 'Total events']}
        rows={buckets.map((bucket) => [formatClock(bucket.bucket_start), bucket.total])}
      />
    </>
  )
}
