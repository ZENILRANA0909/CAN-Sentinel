/**
 * TypeScript mirrors of the backend's response models.
 *
 * These are kept deliberately close to the FastAPI schemas in
 * `backend/app/schemas/`; when an endpoint changes, this file changes with it.
 */

export type ThreatLevel = 'NORMAL' | 'SUSPICIOUS' | 'ATTACK'
export type Severity = 'INFO' | 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
export type AttackType =
  | 'NONE'
  | 'FAKE_SPEED'
  | 'CAN_FLOOD'
  | 'ID_ANOMALY'
  | 'FREQUENCY_ANOMALY'
export type EventStatus = 'NEW' | 'ACKNOWLEDGED' | 'RESOLVED'
export type SimulationMode = 'NORMAL' | 'FAKE_SPEED' | 'CAN_FLOOD' | 'MIXED' | 'CUSTOM'

export interface ApiError {
  error: string
  message: string
  details: Record<string, unknown>
}

export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
  has_more: boolean
}

export interface CanMessage {
  id?: number | null
  timestamp: number
  iso_timestamp: string
  can_id: number
  can_id_hex: string
  is_extended_id: boolean
  dlc: number
  data: string
  channel: string
  direction: string
  source: string
  message_type: string
  flagged: boolean
  threat_level?: ThreatLevel | null
  severity?: Severity | null
  label?: string | null
  decoded: Record<string, string | number | boolean | null>
  attack_types: string[]
}

export interface SecurityEvent {
  id?: number | null
  timestamp: number
  iso_timestamp: string
  attack_type: AttackType
  threat_level: ThreatLevel
  severity: Severity
  detector: string
  can_id?: number | null
  can_id_hex?: string | null
  confidence: number
  description: string
  evidence: Record<string, unknown>
  status: EventStatus
  channel?: string | null
  label?: string | null
}

export interface TopCanId {
  can_id: number
  can_id_hex: string
  label?: string | null
  count: number
  flagged: number
}

export interface TrafficStatistics {
  total_messages: number
  total_bytes: number
  invalid_messages: number
  flagged_messages: number
  current_rate_msg_per_s: number
  average_rate_msg_per_s: number
  peak_rate_msg_per_s: number
  unique_can_ids: number
  window_seconds: number
  uptime_seconds: number
  last_message_at: number | null
  by_source: Record<string, number>
  top_can_ids: TopCanId[]
  stored_messages: number
  messages_by_can_id: TopCanId[]
}

export interface RatePoint {
  timestamp: number
  rate_msg_per_s: number
  attacks: number
  total_messages: number
}

export interface TrafficRate {
  current_rate_msg_per_s: number
  average_rate_msg_per_s: number
  peak_rate_msg_per_s: number
  window_seconds: number
  history: RatePoint[]
  flood_threshold_msg_per_s: number
  flood_suspicious_threshold_msg_per_s: number
}

export interface TimelineBucket {
  bucket_start: number
  total: number
  [severity: string]: number
}

export interface AttackStatistics {
  total_events: number
  events_last_hour: number
  live_attacks_total: number
  active_alerts: number
  threat_level: ThreatLevel
  by_attack_type: Record<string, number>
  by_severity: Record<string, number>
  by_status: Record<string, number>
  by_detector: Record<string, number>
  top_can_ids: TopCanId[]
  timeline: TimelineBucket[]
  bucket_seconds: number
}

export interface DetectorSummary {
  name: string
  attack_type: AttackType
  description: string
  enabled: boolean
  inspections: number
  detections: number
  state: Record<string, unknown>
}

export interface SecuritySummary {
  threat_level: ThreatLevel
  active_alerts: number
  attacks_total: number
  events_stored: number
  events_last_hour: number
  by_attack_type: Record<string, number>
  by_severity: Record<string, number>
  recent_events: SecurityEvent[]
  detectors: DetectorSummary[]
  monitor_running: boolean
  simulation_running: boolean
}

export interface VehicleSnapshot {
  phase: string
  speed_kmh: number
  engine_rpm: number
  gear: number
  throttle_pct: number
  brake_pressed: boolean
  brake_pedal_pct: number
  coolant_temp_c: number
  fuel_level_pct: number
  steering_angle_deg: number
  odometer_km: number
}

export interface SimulationModeOption {
  value: SimulationMode
  label: string
  is_attack: boolean
}

export interface SimulationStatus {
  running: boolean
  mode: SimulationMode
  mode_label: string
  attack_active: boolean
  profile: Record<string, unknown>
  started_at: number | null
  stopped_at: number | null
  last_started: number | null
  uptime_seconds: number
  generated_rate_msg_per_s: number
  messages_generated: number
  normal_messages: number
  attack_messages: number
  errors: number
  last_error: string | null
  vehicle: VehicleSnapshot | null
  available_modes: SimulationModeOption[]
  monitor_started?: boolean | null
  previous_mode?: string | null
}

export interface InterfaceStatus {
  backend: string
  channel: string
  bitrate: number
  state: string
  is_open: boolean
  queue_size: number
  queue_pending: number
  bustype?: string
  statistics: {
    received: number
    sent: number
    dropped: number
    errors: number
    last_error: string | null
  }
}

export interface MonitorStatus {
  running: boolean
  started_at: number | null
  stopped_at: number | null
  uptime_seconds: number
  batches_processed: number
  batch_size: number
  errors: number
  last_error: string | null
  interface: InterfaceStatus | null
  pipeline: Record<string, unknown>
}

export interface SystemStatus {
  service: string
  version: string
  environment: string
  uptime_seconds: number
  started_at: number
  monitor: MonitorStatus
  simulation: SimulationStatus
  detection: {
    enabled: boolean
    analysed_messages: number
    flagged_verdicts: number
    events_emitted: number
    events_suppressed: number
    throttle_keys: number
    by_attack_type: Record<string, number>
    by_severity: Record<string, number>
    detectors: DetectorSummary[]
  }
  traffic: TrafficStatistics
  security: {
    attacks_total: number
    active_alerts: number
    flagged_messages: number
    by_attack_type: Record<string, number>
    by_severity: Record<string, number>
    threat_level: ThreatLevel
    active_alert_window_seconds: number
  }
  websocket: {
    running: boolean
    clients: number
    max_clients: number
    events_published: number
    flush_interval_ms: number
    max_messages_per_flush: number
    buffered_messages: number
    connections: Array<Record<string, unknown>>
  }
  storage: {
    writer: Record<string, number | string | boolean | null>
    retention: Record<string, unknown>
    connected: boolean
  }
  telemetry: Record<string, unknown>
  config_revision: number
}

export interface HealthResponse {
  status: string
  service: string
  version: string
  environment: string
  uptime_seconds: number
  checks: Record<string, Record<string, unknown>>
}

export interface DetectionConfig {
  enabled: boolean
  event_cooldown_seconds: number
  flood_threshold: number
  flood_window_seconds: number
  flood_suspicious_ratio: number
  flood_critical_multiplier: number
  per_id_flood_threshold: number
  speed_can_id: number
  fake_speed_threshold: number
  fake_speed_suspicious_threshold: number
  fake_speed_max_acceleration: number
  allowed_can_ids: number[]
  id_anomaly_escalation_count: number
  id_anomaly_window_seconds: number
  frequency_min_samples: number
  frequency_fast_ratio: number
  frequency_slow_ratio: number
  frequency_attack_ratio: number
}

export interface CanRuntimeConfig {
  interface: string
  channel: string
  bitrate: number
}

export interface RetentionConfig {
  enabled: boolean
  max_messages: number
  max_security_events: number
  max_system_events: number
  max_age_days: number
  persist_can_messages: boolean
}

export interface RuntimeConfig {
  revision: number
  detection: DetectionConfig
  can: CanRuntimeConfig
  retention: RetentionConfig
  changed: string[]
  restart_required: string[]
  defaults_note: string
}

export interface SystemEvent {
  id?: number | null
  timestamp: number
  iso_timestamp: string
  event_type: string
  message: string
  severity: string
  context: Record<string, unknown>
}

/* ---------------------------------------------------------------------- */
/* WebSocket envelope                                                      */
/* ---------------------------------------------------------------------- */

export type StreamEventType =
  | 'CAN_MESSAGE'
  | 'ATTACK_DETECTED'
  | 'TRAFFIC_RATE_UPDATE'
  | 'SYSTEM_STATUS'
  | 'SIMULATION_STATUS'
  | 'MONITOR_STATUS'
  | 'CONFIG_UPDATED'
  | 'PONG'
  | 'ERROR'

export interface StreamEnvelope<T = unknown> {
  event: StreamEventType
  timestamp: string | null
  sequence: number
  data: T
}

export interface CanMessageBatch {
  messages: CanMessage[]
  count: number
  observed: number
  sampled: boolean
  interval_ms: number
}

export interface TrafficRateUpdate {
  timestamp: number
  rate_msg_per_s: number
  attacks: number
  total_messages: number
  active_alerts: number
  attacks_total: number
  threat_level: ThreatLevel
}

export type ConnectionState = 'connecting' | 'open' | 'closed' | 'reconnecting'
