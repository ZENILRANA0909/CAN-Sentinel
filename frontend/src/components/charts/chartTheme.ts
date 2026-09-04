/**
 * Shared chart styling.
 *
 * Recharts cannot read Tailwind classes for its SVG primitives, so the palette
 * is mirrored here as literal values. Keep it in step with tailwind.config.js.
 */
export const CHART = {
  grid: '#1b2434',
  axis: '#61708a',
  axisLine: '#273245',
  accent: '#38bdf8',
  accentFill: 'rgba(56,189,248,0.18)',
  danger: '#ef4444',
  warn: '#f0b429',
  ok: '#22c55e',
  muted: '#64748b',
} as const

export const AXIS_PROPS = {
  stroke: CHART.axis,
  tick: { fill: CHART.axis, fontSize: 10 },
  tickLine: false,
  axisLine: { stroke: CHART.axisLine },
} as const

export const GRID_PROPS = {
  stroke: CHART.grid,
  strokeDasharray: '3 3',
  vertical: false,
} as const
