/**
 * Typed REST client.
 *
 * Every call goes through `request`, which turns the backend's error envelope
 * into an `ApiRequestError` carrying the machine-readable code. Nothing in the
 * UI ever sees a raw `Response`.
 */

import type {
  AttackStatistics,
  CanMessage,
  EventStatus,
  HealthResponse,
  MonitorStatus,
  Page,
  RuntimeConfig,
  SecurityEvent,
  SecuritySummary,
  SimulationMode,
  SimulationStatus,
  SystemEvent,
  SystemStatus,
  TrafficRate,
  TrafficStatistics,
} from '@/types/api'

/** Same-origin by default: the dev server proxies `/api`, production serves both. */
export const API_BASE: string = import.meta.env.VITE_API_BASE_URL ?? '/api'

/** Requests that hang longer than this are aborted so the UI can show an error. */
const REQUEST_TIMEOUT_MS = 15_000

export class ApiRequestError extends Error {
  readonly status: number
  readonly code: string
  readonly details: Record<string, unknown>

  constructor(message: string, status: number, code: string, details: Record<string, unknown> = {}) {
    super(message)
    this.name = 'ApiRequestError'
    this.status = status
    this.code = code
    this.details = details
  }

  /** True when the backend could not be reached at all. */
  get isOffline(): boolean {
    return this.status === 0
  }
}

type QueryValue = string | number | boolean | undefined | null

function buildQuery(params: Record<string, QueryValue> = {}): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    search.append(key, String(value))
  }
  const query = search.toString()
  return query ? `?${query}` : ''
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)

  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      signal: init.signal ?? controller.signal,
      headers: {
        Accept: 'application/json',
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
        ...init.headers,
      },
    })
  } catch (error) {
    // A network failure, a CORS rejection or our own abort all land here.
    const aborted = error instanceof DOMException && error.name === 'AbortError'
    throw new ApiRequestError(
      aborted ? 'The request timed out.' : 'Cannot reach the CAN-Sentinel backend.',
      0,
      aborted ? 'timeout' : 'network_error',
    )
  } finally {
    clearTimeout(timeout)
  }

  if (response.status === 204) return undefined as T

  const text = await response.text()
  let payload: unknown = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = null
    }
  }

  if (!response.ok) {
    const envelope = (payload ?? {}) as Partial<{
      error: string
      message: string
      details: Record<string, unknown>
    }>
    throw new ApiRequestError(
      envelope.message ?? `Request failed with status ${response.status}.`,
      response.status,
      envelope.error ?? 'http_error',
      envelope.details ?? {},
    )
  }

  return payload as T
}

/* ---------------------------------------------------------------------- */
/* System                                                                  */
/* ---------------------------------------------------------------------- */
export const api = {
  health: () => request<HealthResponse>('/health'),
  status: () => request<SystemStatus>('/status'),
  systemEvents: (limit = 50, eventType?: string) =>
    request<SystemEvent[]>(`/system/events${buildQuery({ limit, event_type: eventType })}`),

  /* -------------------------------------------------------------------- */
  /* Traffic                                                               */
  /* -------------------------------------------------------------------- */
  recentMessages: (params: {
    limit?: number
    can_id?: string
    flagged_only?: boolean
    search?: string
  } = {}) => request<CanMessage[]>(`/messages/recent${buildQuery(params)}`),

  messages: (params: {
    limit?: number
    offset?: number
    can_id?: string
    since?: number
    until?: number
    source?: string
    flagged_only?: boolean
    data_contains?: string
  } = {}) => request<Page<CanMessage>>(`/messages${buildQuery(params)}`),

  trafficStatistics: (sinceSeconds?: number) =>
    request<TrafficStatistics>(`/traffic/statistics${buildQuery({ since_seconds: sinceSeconds })}`),

  trafficRate: (points = 120) => request<TrafficRate>(`/traffic/rate${buildQuery({ points })}`),

  /* -------------------------------------------------------------------- */
  /* Security                                                              */
  /* -------------------------------------------------------------------- */
  attacks: (params: {
    limit?: number
    offset?: number
    attack_type?: string
    severity?: string
    status?: string
    detector?: string
    can_id?: string
    since?: number
  } = {}) => request<Page<SecurityEvent>>(`/attacks${buildQuery(params)}`),

  recentAttacks: (limit = 50) => request<SecurityEvent[]>(`/attacks/recent${buildQuery({ limit })}`),

  attackStatistics: (params: { since_seconds?: number; bucket_seconds?: number; buckets?: number } = {}) =>
    request<AttackStatistics>(`/attacks/statistics${buildQuery(params)}`),

  securitySummary: (limit = 10) =>
    request<SecuritySummary>(`/security/summary${buildQuery({ limit })}`),

  updateAttackStatus: (eventId: number, status: EventStatus) =>
    request<SecurityEvent>(`/attacks/${eventId}`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    }),

  /* -------------------------------------------------------------------- */
  /* Simulation                                                            */
  /* -------------------------------------------------------------------- */
  simulationStatus: () => request<SimulationStatus>('/simulation/status'),

  startSimulation: (body: SimulationRequestBody = {}) =>
    request<SimulationStatus>('/simulation/start', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  stopSimulation: () => request<SimulationStatus>('/simulation/stop', { method: 'POST' }),

  setSimulationMode: (body: SimulationRequestBody) =>
    request<SimulationStatus>('/simulation/mode', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  resetSimulation: () => request<SimulationStatus>('/simulation/reset', { method: 'POST' }),

  injectFrame: (body: { can_id: number; data: string; is_extended_id?: boolean }) =>
    request<CanMessage>('/simulation/inject', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  /* -------------------------------------------------------------------- */
  /* Monitor                                                               */
  /* -------------------------------------------------------------------- */
  monitorStatus: () => request<MonitorStatus>('/monitor/status'),
  startMonitor: () => request<MonitorStatus>('/monitor/start', { method: 'POST' }),
  stopMonitor: () => request<MonitorStatus>('/monitor/stop', { method: 'POST' }),

  /* -------------------------------------------------------------------- */
  /* Configuration                                                         */
  /* -------------------------------------------------------------------- */
  config: () => request<RuntimeConfig>('/config'),
  updateConfig: (body: ConfigPatchBody) =>
    request<RuntimeConfig>('/config', { method: 'PUT', body: JSON.stringify(body) }),
  resetConfig: () => request<RuntimeConfig>('/config/reset', { method: 'POST' }),
}

export interface SimulationRequestBody {
  mode?: SimulationMode
  flood_rate?: number
  flood_can_id?: number
  fake_speed_value?: number
  fake_speed_rate?: number
  traffic_scale?: number
  custom_frames?: Array<{
    can_id: number
    data: string
    interval_ms: number
    is_extended_id?: boolean
  }>
}

export interface ConfigPatchBody {
  detection?: Partial<Record<string, number | boolean | number[]>>
  can?: Partial<Record<string, string | number>>
  retention?: Partial<Record<string, number | boolean>>
}

/** WebSocket URL for the live stream, derived from the current page origin. */
export function streamUrl(): string {
  const explicit = import.meta.env.VITE_WS_URL
  if (explicit) return explicit
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/ws/traffic`
}
