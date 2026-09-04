import type { AttackType, Severity, ThreatLevel } from '@/types/api'

/* ---------------------------------------------------------------------- */
/* Numbers                                                                 */
/* ---------------------------------------------------------------------- */

export function formatNumber(value: number | null | undefined, fractionDigits = 0): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return value.toLocaleString(undefined, {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  })
}

/** Large counters read better abbreviated in a tile than as seven digits. */
export function formatCompact(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  if (Math.abs(value) < 10_000) return formatNumber(value)
  return value.toLocaleString(undefined, { notation: 'compact', maximumFractionDigits: 1 })
}

export function formatRate(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return value >= 100 ? formatNumber(value) : formatNumber(value, 1)
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes)) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`
}

export function formatPercent(value: number | null | undefined, fractionDigits = 0): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return `${(value * 100).toFixed(fractionDigits)}%`
}

/* ---------------------------------------------------------------------- */
/* Time                                                                    */
/* ---------------------------------------------------------------------- */

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds) || seconds < 0) {
    return '—'
  }
  const total = Math.floor(seconds)
  const days = Math.floor(total / 86_400)
  const hours = Math.floor((total % 86_400) / 3_600)
  const minutes = Math.floor((total % 3_600) / 60)
  const secs = total % 60
  if (days > 0) return `${days}d ${hours}h ${minutes}m`
  if (hours > 0) return `${hours}h ${minutes}m ${secs}s`
  if (minutes > 0) return `${minutes}m ${secs}s`
  return `${secs}s`
}

/** Wall-clock time with milliseconds — what a bus trace is normally read by. */
export function formatClock(epochSeconds: number | null | undefined): string {
  if (epochSeconds === null || epochSeconds === undefined || !Number.isFinite(epochSeconds)) {
    return '—'
  }
  const date = new Date(epochSeconds * 1000)
  const time = date.toLocaleTimeString(undefined, { hour12: false })
  return `${time}.${String(date.getMilliseconds()).padStart(3, '0')}`
}

export function formatDateTime(epochSeconds: number | null | undefined): string {
  if (epochSeconds === null || epochSeconds === undefined || !Number.isFinite(epochSeconds)) {
    return '—'
  }
  return new Date(epochSeconds * 1000).toLocaleString(undefined, { hour12: false })
}

export function formatRelative(epochSeconds: number | null | undefined): string {
  if (epochSeconds === null || epochSeconds === undefined || !Number.isFinite(epochSeconds)) {
    return 'never'
  }
  const delta = Date.now() / 1000 - epochSeconds
  if (delta < 1) return 'just now'
  if (delta < 60) return `${Math.floor(delta)}s ago`
  if (delta < 3_600) return `${Math.floor(delta / 60)}m ago`
  if (delta < 86_400) return `${Math.floor(delta / 3_600)}h ago`
  return `${Math.floor(delta / 86_400)}d ago`
}

/* ---------------------------------------------------------------------- */
/* CAN                                                                     */
/* ---------------------------------------------------------------------- */

export function formatCanId(canId: number | null | undefined, extended = false): string {
  if (canId === null || canId === undefined) return '—'
  return `0x${canId.toString(16).toUpperCase().padStart(extended ? 8 : 3, '0')}`
}

/** Space bytes into pairs so a payload can be read at a glance. */
export function formatPayload(hex: string | null | undefined): string {
  if (!hex) return '—'
  return hex.match(/.{1,2}/g)?.join(' ') ?? hex
}

/** Render a decoded signal name as a human label. */
export function humanizeSignal(name: string): string {
  return name
    .replace(/_kmh$/, ' (km/h)')
    .replace(/_pct$/, ' (%)')
    .replace(/_c$/, ' (°C)')
    .replace(/_dps$/, ' (°/s)')
    .replace(/_deg$/, ' (°)')
    .replace(/_nm$/, ' (Nm)')
    .replace(/_bar$/, ' (bar)')
    .replace(/_rpm$/, ' (rpm)')
    .replace(/_/g, ' ')
    .replace(/^\w/, (character) => character.toUpperCase())
}

/* ---------------------------------------------------------------------- */
/* Domain vocabulary                                                       */
/* ---------------------------------------------------------------------- */

export interface Tone {
  label: string
  /** Tailwind classes for a filled badge. */
  badge: string
  /** Tailwind text colour for standalone use. */
  text: string
  /** Hex colour for charts, which cannot use Tailwind classes. */
  hex: string
}

const SEVERITY_TONES: Record<Severity, Tone> = {
  INFO: {
    label: 'Info',
    badge: 'bg-severity-info/15 text-slate-300 ring-1 ring-inset ring-severity-info/40',
    text: 'text-slate-300',
    hex: '#64748b',
  },
  LOW: {
    label: 'Low',
    badge: 'bg-severity-low/15 text-sky-300 ring-1 ring-inset ring-severity-low/40',
    text: 'text-sky-300',
    hex: '#38bdf8',
  },
  MEDIUM: {
    label: 'Medium',
    badge: 'bg-severity-medium/15 text-amber-300 ring-1 ring-inset ring-severity-medium/40',
    text: 'text-amber-300',
    hex: '#f0b429',
  },
  HIGH: {
    label: 'High',
    badge: 'bg-severity-high/15 text-orange-300 ring-1 ring-inset ring-severity-high/45',
    text: 'text-orange-300',
    hex: '#f97316',
  },
  CRITICAL: {
    label: 'Critical',
    badge: 'bg-severity-critical/20 text-red-300 ring-1 ring-inset ring-severity-critical/55',
    text: 'text-red-300',
    hex: '#ef4444',
  },
}

export function severityTone(severity: Severity | string | null | undefined): Tone {
  return SEVERITY_TONES[(severity as Severity) ?? 'INFO'] ?? SEVERITY_TONES.INFO
}

export const SEVERITY_ORDER: Severity[] = ['INFO', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL']

const THREAT_TONES: Record<ThreatLevel, Tone> = {
  NORMAL: {
    label: 'Normal',
    badge: 'bg-state-ok/15 text-emerald-300 ring-1 ring-inset ring-state-ok/40',
    text: 'text-emerald-300',
    hex: '#22c55e',
  },
  SUSPICIOUS: {
    label: 'Suspicious',
    badge: 'bg-state-warn/15 text-amber-300 ring-1 ring-inset ring-state-warn/45',
    text: 'text-amber-300',
    hex: '#f0b429',
  },
  ATTACK: {
    label: 'Under attack',
    badge: 'bg-state-bad/20 text-red-300 ring-1 ring-inset ring-state-bad/55',
    text: 'text-red-300',
    hex: '#ef4444',
  },
}

export function threatTone(level: ThreatLevel | string | null | undefined): Tone {
  return THREAT_TONES[(level as ThreatLevel) ?? 'NORMAL'] ?? THREAT_TONES.NORMAL
}

const ATTACK_LABELS: Record<AttackType, string> = {
  NONE: 'None',
  FAKE_SPEED: 'Fake Speed',
  CAN_FLOOD: 'CAN Flood',
  ID_ANOMALY: 'ID Anomaly',
  FREQUENCY_ANOMALY: 'Frequency Anomaly',
}

export function attackLabel(type: AttackType | string | null | undefined): string {
  return ATTACK_LABELS[(type as AttackType) ?? 'NONE'] ?? String(type ?? 'Unknown')
}

/** Distinct, colour-blind-safe hues for the attack-distribution charts. */
export const ATTACK_COLORS: Record<string, string> = {
  FAKE_SPEED: '#f97316',
  CAN_FLOOD: '#ef4444',
  ID_ANOMALY: '#a78bfa',
  FREQUENCY_ANOMALY: '#38bdf8',
  NONE: '#64748b',
}

export function attackColor(type: string): string {
  return ATTACK_COLORS[type] ?? '#64748b'
}

export function detectorLabel(name: string): string {
  return name
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}
