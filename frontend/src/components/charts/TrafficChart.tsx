import {
  Area,
  Bar,
  CartesianGrid,
  ComposedChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { ChartDescription, TooltipCard } from './ChartPrimitives'
import { AXIS_PROPS, CHART, GRID_PROPS } from './chartTheme'
import { EmptyState } from '@/components/ui/States'
import { formatClock, formatRate } from '@/utils/format'
import type { RatePoint } from '@/types/api'

interface TrafficChartProps {
  data: RatePoint[]
  floodThreshold?: number
  suspiciousThreshold?: number
  height?: number
  /** Overlay per-second attack counts as bars. */
  showAttacks?: boolean
}

/**
 * Bus load over time with the flood thresholds drawn in.
 *
 * The threshold lines are the point of the chart: they turn "the rate went up"
 * into "the rate crossed the line the detector fires on".
 */
export function TrafficChart({
  data,
  floodThreshold,
  suspiciousThreshold,
  height = 240,
  showAttacks = true,
}: TrafficChartProps) {
  if (data.length === 0) {
    return (
      <EmptyState
        title="No traffic yet"
        description="Start the simulator, or connect a CAN interface, to see live bus load."
      />
    )
  }

  const peak = Math.max(...data.map((point) => point.rate_msg_per_s), floodThreshold ?? 0)
  const attackPeak = Math.max(...data.map((point) => point.attacks), 1)

  return (
    <>
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -8 }}>
            <defs>
              <linearGradient id="rateFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={CHART.accent} stopOpacity={0.35} />
                <stop offset="100%" stopColor={CHART.accent} stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid {...GRID_PROPS} />
            <XAxis
              dataKey="timestamp"
              {...AXIS_PROPS}
              minTickGap={48}
              tickFormatter={(value: number) => formatClock(value).slice(0, 8)}
            />
            <YAxis
              {...AXIS_PROPS}
              width={48}
              domain={[0, Math.ceil(peak * 1.15)]}
              tickFormatter={(value: number) => formatRate(value)}
            />
            {showAttacks && (
              <YAxis yAxisId="attacks" hide domain={[0, attackPeak * 4]} />
            )}
            <Tooltip
              cursor={{ stroke: CHART.axisLine }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null
                const point = payload[0].payload as RatePoint
                return (
                  <TooltipCard
                    title={formatClock(point.timestamp)}
                    rows={[
                      {
                        label: 'Bus rate',
                        value: `${formatRate(point.rate_msg_per_s)} msg/s`,
                        color: CHART.accent,
                      },
                      { label: 'Alerts', value: point.attacks, color: CHART.danger },
                      { label: 'Total frames', value: point.total_messages.toLocaleString() },
                    ]}
                  />
                )
              }}
            />
            {suspiciousThreshold !== undefined && suspiciousThreshold > 0 && (
              <ReferenceLine
                y={suspiciousThreshold}
                stroke={CHART.warn}
                strokeDasharray="4 4"
                strokeOpacity={0.75}
                label={{
                  value: 'suspicious',
                  position: 'insideTopRight',
                  fill: CHART.warn,
                  fontSize: 9,
                }}
              />
            )}
            {floodThreshold !== undefined && floodThreshold > 0 && (
              <ReferenceLine
                y={floodThreshold}
                stroke={CHART.danger}
                strokeDasharray="4 4"
                label={{
                  value: 'flood threshold',
                  position: 'insideTopRight',
                  fill: CHART.danger,
                  fontSize: 9,
                }}
              />
            )}
            {showAttacks && (
              <Bar
                yAxisId="attacks"
                dataKey="attacks"
                fill={CHART.danger}
                fillOpacity={0.55}
                barSize={4}
                isAnimationActive={false}
              />
            )}
            <Area
              type="monotone"
              dataKey="rate_msg_per_s"
              stroke={CHART.accent}
              strokeWidth={1.75}
              fill="url(#rateFill)"
              isAnimationActive={false}
              dot={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <ChartDescription
        caption="Bus message rate over time"
        headers={['Time', 'Messages per second', 'Alerts']}
        rows={data
          .slice(-20)
          .map((point) => [formatClock(point.timestamp), point.rate_msg_per_s, point.attacks])}
      />
    </>
  )
}
