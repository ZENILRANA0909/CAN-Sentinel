import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { LiveStatusContext, LiveTrafficContext } from '@/hooks/liveData'
import { streamUrl } from '@/services/api'
import type {
  CanMessage,
  CanMessageBatch,
  ConnectionState,
  MonitorStatus,
  RatePoint,
  SecurityEvent,
  SimulationStatus,
  StreamEnvelope,
  SystemStatus,
  ThreatLevel,
  TrafficRateUpdate,
} from '@/types/api'

/** Frames kept in memory for the live table. */
const MESSAGE_BUFFER = 400
/** Alerts kept in memory for the dashboard feed. */
const ALERT_BUFFER = 120
/** Rate points kept for the live chart (~3 minutes at one per second). */
const RATE_BUFFER = 180

const RECONNECT_BASE_MS = 1_000
const RECONNECT_MAX_MS = 15_000
const HEARTBEAT_MS = 25_000

function ring<T>(previous: T[], incoming: T[], limit: number): T[] {
  if (incoming.length === 0) return previous
  const next = incoming.length >= limit ? incoming.slice(-limit) : [...previous, ...incoming]
  return next.length > limit ? next.slice(next.length - limit) : next
}

/**
 * Owns the single WebSocket connection for the whole dashboard.
 *
 * Reconnection is automatic with exponential backoff and jitter; a heartbeat
 * keeps intermediaries from closing an idle socket. Nothing here throws into
 * the render tree - a dead backend surfaces as a connection state the UI can
 * render a banner for.
 */
export function LiveDataProvider({ children }: { children: ReactNode }) {
  const [connection, setConnection] = useState<ConnectionState>('connecting')
  const [reconnectAttempts, setReconnectAttempts] = useState(0)
  const [lastEventAt, setLastEventAt] = useState<number | null>(null)

  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null)
  const [monitorStatus, setMonitorStatus] = useState<MonitorStatus | null>(null)
  const [simulationStatus, setSimulationStatus] = useState<SimulationStatus | null>(null)
  const [alerts, setAlerts] = useState<SecurityEvent[]>([])
  const [rateHistory, setRateHistory] = useState<RatePoint[]>([])
  const [liveCounters, setLiveCounters] = useState({
    currentRate: 0,
    activeAlerts: 0,
    attacksTotal: 0,
    threatLevel: 'NORMAL' as ThreatLevel,
  })
  const [alertPulse, setAlertPulse] = useState(0)
  const [configRevision, setConfigRevision] = useState(0)

  const [messages, setMessages] = useState<CanMessage[]>([])
  const [flush, setFlush] = useState({ observed: 0, sampled: false, total: 0 })

  const socketRef = useRef<WebSocket | null>(null)
  const retryTimer = useRef<number | null>(null)
  const heartbeat = useRef<number | null>(null)
  const attemptRef = useRef(0)
  const disposed = useRef(false)

  const clearTimers = useCallback(() => {
    if (retryTimer.current !== null) {
      window.clearTimeout(retryTimer.current)
      retryTimer.current = null
    }
    if (heartbeat.current !== null) {
      window.clearInterval(heartbeat.current)
      heartbeat.current = null
    }
  }, [])

  const handleEvent = useCallback((envelope: StreamEnvelope) => {
    setLastEventAt(Date.now())
    switch (envelope.event) {
      case 'CAN_MESSAGE': {
        const batch = envelope.data as CanMessageBatch
        setMessages((previous) => ring(previous, batch.messages ?? [], MESSAGE_BUFFER))
        setFlush((previous) => ({
          observed: batch.observed ?? 0,
          sampled: Boolean(batch.sampled),
          total: previous.total + (batch.observed ?? 0),
        }))
        break
      }
      case 'ATTACK_DETECTED': {
        const alert = envelope.data as SecurityEvent
        setAlerts((previous) => [alert, ...previous].slice(0, ALERT_BUFFER))
        setAlertPulse((value) => value + 1)
        break
      }
      case 'TRAFFIC_RATE_UPDATE': {
        const update = envelope.data as TrafficRateUpdate
        setRateHistory((previous) =>
          ring(
            previous,
            [
              {
                timestamp: update.timestamp,
                rate_msg_per_s: update.rate_msg_per_s,
                attacks: update.attacks,
                total_messages: update.total_messages,
              },
            ],
            RATE_BUFFER,
          ),
        )
        setLiveCounters({
          currentRate: update.rate_msg_per_s,
          activeAlerts: update.active_alerts,
          attacksTotal: update.attacks_total,
          threatLevel: update.threat_level,
        })
        break
      }
      case 'SYSTEM_STATUS': {
        const status = envelope.data as SystemStatus
        setSystemStatus(status)
        setMonitorStatus(status.monitor)
        setSimulationStatus(status.simulation)
        setLiveCounters((previous) => ({
          ...previous,
          activeAlerts: status.security.active_alerts,
          attacksTotal: status.security.attacks_total,
          threatLevel: status.security.threat_level,
        }))
        break
      }
      case 'SIMULATION_STATUS':
        setSimulationStatus(envelope.data as SimulationStatus)
        break
      case 'MONITOR_STATUS':
        setMonitorStatus(envelope.data as MonitorStatus)
        break
      case 'CONFIG_UPDATED':
        setConfigRevision((envelope.data as { revision: number }).revision)
        break
      default:
        break
    }
  }, [])

  const connect = useCallback(() => {
    if (disposed.current) return
    clearTimers()

    setConnection(attemptRef.current === 0 ? 'connecting' : 'reconnecting')

    let socket: WebSocket
    try {
      socket = new WebSocket(streamUrl())
    } catch {
      scheduleRetry()
      return
    }
    socketRef.current = socket

    socket.onopen = () => {
      attemptRef.current = 0
      setReconnectAttempts(0)
      setConnection('open')
      heartbeat.current = window.setInterval(() => {
        if (socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ action: 'ping', id: Date.now() }))
        }
      }, HEARTBEAT_MS)
    }

    socket.onmessage = (raw) => {
      try {
        handleEvent(JSON.parse(raw.data as string) as StreamEnvelope)
      } catch {
        // A malformed frame is dropped rather than breaking the stream.
      }
    }

    socket.onerror = () => {
      // `onclose` always follows, which is where the retry is scheduled.
    }

    socket.onclose = () => {
      socketRef.current = null
      clearTimers()
      if (disposed.current) return
      setConnection('reconnecting')
      scheduleRetry()
    }

    function scheduleRetry() {
      attemptRef.current += 1
      setReconnectAttempts(attemptRef.current)
      const backoff = Math.min(RECONNECT_BASE_MS * 2 ** (attemptRef.current - 1), RECONNECT_MAX_MS)
      // Jitter avoids every open tab reconnecting in lockstep.
      const delay = backoff * (0.75 + Math.random() * 0.5)
      retryTimer.current = window.setTimeout(connect, delay)
    }
  }, [clearTimers, handleEvent])

  const reconnect = useCallback(() => {
    attemptRef.current = 0
    setReconnectAttempts(0)
    socketRef.current?.close()
    socketRef.current = null
    connect()
  }, [connect])

  useEffect(() => {
    disposed.current = false
    connect()
    return () => {
      disposed.current = true
      clearTimers()
      const socket = socketRef.current
      socketRef.current = null
      socket?.close()
    }
  }, [connect, clearTimers])

  const clearMessages = useCallback(() => setMessages([]), [])

  const statusValue = useMemo(
    () => ({
      connection,
      reconnectAttempts,
      lastEventAt,
      systemStatus,
      monitorStatus,
      simulationStatus,
      alerts,
      rateHistory,
      currentRate: liveCounters.currentRate,
      activeAlerts: liveCounters.activeAlerts,
      attacksTotal: liveCounters.attacksTotal,
      threatLevel: liveCounters.threatLevel,
      alertPulse,
      configRevision,
      reconnect,
    }),
    [
      connection,
      reconnectAttempts,
      lastEventAt,
      systemStatus,
      monitorStatus,
      simulationStatus,
      alerts,
      rateHistory,
      liveCounters,
      alertPulse,
      configRevision,
      reconnect,
    ],
  )

  const trafficValue = useMemo(
    () => ({
      messages,
      observedInLastFlush: flush.observed,
      sampled: flush.sampled,
      totalReceived: flush.total,
      clear: clearMessages,
    }),
    [messages, flush, clearMessages],
  )

  return (
    <LiveStatusContext.Provider value={statusValue}>
      <LiveTrafficContext.Provider value={trafficValue}>{children}</LiveTrafficContext.Provider>
    </LiveStatusContext.Provider>
  )
}
