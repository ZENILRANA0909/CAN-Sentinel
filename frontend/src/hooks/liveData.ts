import { createContext, useContext } from 'react'
import type {
  CanMessage,
  ConnectionState,
  MonitorStatus,
  RatePoint,
  SecurityEvent,
  SimulationStatus,
  SystemStatus,
  ThreatLevel,
} from '@/types/api'

/**
 * The live stream is split across two contexts on purpose.
 *
 * Raw CAN frames arrive several times a second; status and alerts change far
 * less often. Keeping them apart means a page that only shows counters and
 * charts does not re-render on every frame batch.
 */

export interface LiveStatusValue {
  connection: ConnectionState
  /** Consecutive failed connection attempts; drives the reconnect banner. */
  reconnectAttempts: number
  lastEventAt: number | null
  systemStatus: SystemStatus | null
  monitorStatus: MonitorStatus | null
  simulationStatus: SimulationStatus | null
  alerts: SecurityEvent[]
  rateHistory: RatePoint[]
  currentRate: number
  activeAlerts: number
  attacksTotal: number
  threatLevel: ThreatLevel
  /** Increments on every new alert, so views can trigger a one-shot animation. */
  alertPulse: number
  configRevision: number
  reconnect: () => void
}

export interface LiveTrafficValue {
  messages: CanMessage[]
  /** Frames the backend observed in the last flush, including those not sent. */
  observedInLastFlush: number
  sampled: boolean
  totalReceived: number
  clear: () => void
}

export const LiveStatusContext = createContext<LiveStatusValue | null>(null)
export const LiveTrafficContext = createContext<LiveTrafficValue | null>(null)

export function useLiveStatus(): LiveStatusValue {
  const value = useContext(LiveStatusContext)
  if (!value) throw new Error('useLiveStatus must be used inside <LiveDataProvider>')
  return value
}

export function useLiveTraffic(): LiveTrafficValue {
  const value = useContext(LiveTrafficContext)
  if (!value) throw new Error('useLiveTraffic must be used inside <LiveDataProvider>')
  return value
}
