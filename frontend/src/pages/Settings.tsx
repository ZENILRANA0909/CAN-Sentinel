import { AlertTriangle, RotateCcw, Save, SlidersHorizontal } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Pill } from '@/components/ui/Badge'
import { Button, Field, Select, TextInput, Toggle } from '@/components/ui/Controls'
import { Panel } from '@/components/ui/Panel'
import { ErrorState, LoadingState } from '@/components/ui/States'
import { usePolledResource } from '@/hooks/usePolledResource'
import { ApiRequestError, api, type ConfigPatchBody } from '@/services/api'
import { formatCanId } from '@/utils/format'
import type { RuntimeConfig } from '@/types/api'

/** Editable mirror of the runtime configuration, held as strings while typing. */
interface Draft {
  flood_threshold: string
  flood_window_seconds: string
  flood_suspicious_ratio: string
  flood_critical_multiplier: string
  per_id_flood_threshold: string
  fake_speed_threshold: string
  fake_speed_suspicious_threshold: string
  fake_speed_max_acceleration: string
  speed_can_id: string
  allowed_can_ids: string
  id_anomaly_escalation_count: string
  id_anomaly_window_seconds: string
  frequency_fast_ratio: string
  frequency_slow_ratio: string
  frequency_attack_ratio: string
  frequency_min_samples: string
  event_cooldown_seconds: string
  detection_enabled: boolean
  can_interface: string
  can_channel: string
  can_bitrate: string
  retention_enabled: boolean
  persist_can_messages: boolean
  max_messages: string
  max_security_events: string
  max_age_days: string
}

function toDraft(config: RuntimeConfig): Draft {
  const { detection, can, retention } = config
  return {
    flood_threshold: String(detection.flood_threshold),
    flood_window_seconds: String(detection.flood_window_seconds),
    flood_suspicious_ratio: String(detection.flood_suspicious_ratio),
    flood_critical_multiplier: String(detection.flood_critical_multiplier),
    per_id_flood_threshold: String(detection.per_id_flood_threshold),
    fake_speed_threshold: String(detection.fake_speed_threshold),
    fake_speed_suspicious_threshold: String(detection.fake_speed_suspicious_threshold),
    fake_speed_max_acceleration: String(detection.fake_speed_max_acceleration),
    speed_can_id: formatCanId(detection.speed_can_id),
    allowed_can_ids: detection.allowed_can_ids.map((id) => formatCanId(id)).join(', '),
    id_anomaly_escalation_count: String(detection.id_anomaly_escalation_count),
    id_anomaly_window_seconds: String(detection.id_anomaly_window_seconds),
    frequency_fast_ratio: String(detection.frequency_fast_ratio),
    frequency_slow_ratio: String(detection.frequency_slow_ratio),
    frequency_attack_ratio: String(detection.frequency_attack_ratio),
    frequency_min_samples: String(detection.frequency_min_samples),
    event_cooldown_seconds: String(detection.event_cooldown_seconds),
    detection_enabled: detection.enabled,
    can_interface: can.interface,
    can_channel: can.channel,
    can_bitrate: String(can.bitrate),
    retention_enabled: retention.enabled,
    persist_can_messages: retention.persist_can_messages,
    max_messages: String(retention.max_messages),
    max_security_events: String(retention.max_security_events),
    max_age_days: String(retention.max_age_days),
  }
}

function parseCanIdList(raw: string): number[] {
  return raw
    .split(/[,\s]+/)
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => (part.toLowerCase().startsWith('0x') ? parseInt(part, 16) : Number(part)))
    .filter((value) => Number.isFinite(value) && value >= 0)
}

function parseCanId(raw: string): number {
  const text = raw.trim().toLowerCase()
  return text.startsWith('0x') ? parseInt(text, 16) : Number(text)
}

export function SettingsPage() {
  const config = usePolledResource(() => api.config(), [], { intervalMs: 0 })
  const [draft, setDraft] = useState<Draft | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<RuntimeConfig | null>(null)

  useEffect(() => {
    if (config.data) setDraft(toDraft(config.data))
  }, [config.data])

  if (config.loading && !draft) return <LoadingState label="Loading configuration…" />
  if (config.error && !draft) return <ErrorState error={config.error} onRetry={config.refetch} />
  if (!draft) return <LoadingState />

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((previous) => (previous ? { ...previous, [key]: value } : previous))

  const numeric = (value: string) => {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : undefined
  }

  const save = async () => {
    setSaving(true)
    setError(null)
    setResult(null)
    const body: ConfigPatchBody = {
      detection: {
        enabled: draft.detection_enabled,
        event_cooldown_seconds: numeric(draft.event_cooldown_seconds),
        flood_threshold: numeric(draft.flood_threshold),
        flood_window_seconds: numeric(draft.flood_window_seconds),
        flood_suspicious_ratio: numeric(draft.flood_suspicious_ratio),
        flood_critical_multiplier: numeric(draft.flood_critical_multiplier),
        per_id_flood_threshold: numeric(draft.per_id_flood_threshold),
        fake_speed_threshold: numeric(draft.fake_speed_threshold),
        fake_speed_suspicious_threshold: numeric(draft.fake_speed_suspicious_threshold),
        fake_speed_max_acceleration: numeric(draft.fake_speed_max_acceleration),
        speed_can_id: parseCanId(draft.speed_can_id),
        allowed_can_ids: parseCanIdList(draft.allowed_can_ids),
        id_anomaly_escalation_count: numeric(draft.id_anomaly_escalation_count),
        id_anomaly_window_seconds: numeric(draft.id_anomaly_window_seconds),
        frequency_fast_ratio: numeric(draft.frequency_fast_ratio),
        frequency_slow_ratio: numeric(draft.frequency_slow_ratio),
        frequency_attack_ratio: numeric(draft.frequency_attack_ratio),
        frequency_min_samples: numeric(draft.frequency_min_samples),
      },
      can: {
        interface: draft.can_interface,
        channel: draft.can_channel,
        bitrate: numeric(draft.can_bitrate),
      },
      retention: {
        enabled: draft.retention_enabled,
        persist_can_messages: draft.persist_can_messages,
        max_messages: numeric(draft.max_messages),
        max_security_events: numeric(draft.max_security_events),
        max_age_days: numeric(draft.max_age_days),
      },
    }
    try {
      const updated = await api.updateConfig(body)
      setResult(updated)
      await config.refetch()
    } catch (caught) {
      setError(
        caught instanceof ApiRequestError
          ? `${caught.message}${caught.code === 'configuration_error' ? ' — nothing was applied.' : ''}`
          : 'Could not save the configuration.',
      )
    } finally {
      setSaving(false)
    }
  }

  const restore = async () => {
    setSaving(true)
    setError(null)
    setResult(null)
    try {
      const restored = await api.resetConfig()
      setDraft(toDraft(restored))
      setResult(restored)
      await config.refetch()
    } catch (caught) {
      setError(caught instanceof ApiRequestError ? caught.message : 'Could not reset the configuration.')
    } finally {
      setSaving(false)
    }
  }

  const numberField = (
    key: keyof Draft,
    label: string,
    hint: string,
    step = 'any',
  ) => (
    <Field label={label} hint={hint}>
      {(id, describedBy) => (
        <TextInput
          id={id}
          aria-describedby={describedBy}
          type="number"
          step={step}
          value={String(draft[key])}
          onChange={(event) => set(key, event.target.value as Draft[typeof key])}
        />
      )}
    </Field>
  )

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-amber-500/35 bg-amber-500/10 px-4 py-3">
        <p className="flex items-start gap-2 text-xs text-amber-100">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <span>
            These thresholds are <strong>demonstration values</strong>, chosen so attacks are visible
            within seconds on a laptop. They are not derived from any vehicle safety standard and
            must not be treated as safety limits. Detection changes take effect on the next frame;
            bus changes apply the next time the monitor starts.
          </span>
        </p>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2">
          <Pill>Revision {config.data?.revision ?? '—'}</Pill>
          {result?.changed?.length ? <Pill>{result.changed.length} field(s) changed</Pill> : null}
          {result?.restart_required?.length ? (
            <Pill className="bg-amber-500/15 text-amber-300 ring-amber-500/40">
              Restart the monitor to apply: {result.restart_required.join(', ')}
            </Pill>
          ) : null}
        </div>
        <div className="flex gap-2">
          <Button variant="ghost" onClick={restore} loading={saving} icon={<RotateCcw className="h-3.5 w-3.5" />}>
            Restore defaults
          </Button>
          <Button variant="primary" onClick={save} loading={saving} icon={<Save className="h-3.5 w-3.5" />}>
            Save configuration
          </Button>
        </div>
      </div>

      {error && (
        <p role="alert" className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-200">
          {error}
        </p>
      )}
      {result && !error && (
        <p role="status" className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200">
          Configuration saved (revision {result.revision}).
          {result.changed.length === 0 && ' No values differed from the current configuration.'}
        </p>
      )}

      <Panel title="Detection engine" icon={<SlidersHorizontal className="h-4 w-4" />}>
        <Toggle
          checked={draft.detection_enabled}
          onChange={(value) => set('detection_enabled', value)}
          label="Detection enabled"
          description="When off, frames still flow and are recorded, but no detector runs."
        />
        <div className="mt-3">
          {numberField(
            'event_cooldown_seconds',
            'Event cooldown (s)',
            'One event per condition per cooldown; an escalation is always reported immediately.',
          )}
        </div>
      </Panel>

      <Panel title="CAN flood detector" subtitle="Rolling-window rate thresholds">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {numberField('flood_threshold', 'Flood threshold (msg/s)', 'Above this the bus rate is an attack.')}
          {numberField('flood_window_seconds', 'Window (s)', 'Rolling window the rate is measured over.')}
          {numberField('flood_suspicious_ratio', 'Suspicious ratio', 'Fraction of the threshold that is already suspicious.')}
          {numberField('flood_critical_multiplier', 'Critical multiplier', 'Multiple of the threshold that escalates to CRITICAL.')}
          {numberField('per_id_flood_threshold', 'Per-identifier threshold (msg/s)', 'Catches a targeted flood on a single ID.')}
        </div>
      </Panel>

      <Panel title="Fake speed detector" subtitle="Magnitude and plausibility limits">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {numberField('fake_speed_threshold', 'Attack threshold (km/h)', 'Speeds above this are reported as an attack.')}
          {numberField(
            'fake_speed_suspicious_threshold',
            'Suspicious threshold (km/h)',
            'Must be less than or equal to the attack threshold.',
          )}
          {numberField(
            'fake_speed_max_acceleration',
            'Max acceleration (km/h/s)',
            'A larger change between samples is physically implausible.',
          )}
          <Field label="Speed CAN identifier" hint="The frame carrying vehicle speed">
            {(id, describedBy) => (
              <TextInput
                id={id}
                aria-describedby={describedBy}
                value={draft.speed_can_id}
                onChange={(event) => set('speed_can_id', event.target.value)}
              />
            )}
          </Field>
        </div>
      </Panel>

      <Panel title="Identifier anomaly detector" subtitle="Which identifiers are expected on this bus">
        <Field
          label="Allowed CAN identifiers"
          hint="Comma separated, hex or decimal. Anything outside this list is reported."
        >
          {(id, describedBy) => (
            <TextInput
              id={id}
              aria-describedby={describedBy}
              value={draft.allowed_can_ids}
              onChange={(event) => set('allowed_can_ids', event.target.value)}
            />
          )}
        </Field>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          {numberField(
            'id_anomaly_escalation_count',
            'Escalation count',
            'Sightings within the window that escalate SUSPICIOUS to ATTACK.',
            '1',
          )}
          {numberField('id_anomaly_window_seconds', 'Window (s)', 'How long sightings are counted for.')}
        </div>
      </Panel>

      <Panel title="Frequency anomaly detector" subtitle="How far a period may drift from its baseline">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {numberField('frequency_fast_ratio', 'Fast ratio', 'Times faster than baseline before flagging.')}
          {numberField('frequency_attack_ratio', 'Attack ratio', 'Times faster before escalating to ATTACK.')}
          {numberField('frequency_slow_ratio', 'Slow ratio', 'Times slower than baseline before flagging.')}
          {numberField('frequency_min_samples', 'Minimum samples', 'Intervals needed before judging.', '1')}
        </div>
      </Panel>

      <Panel title="CAN bus" subtitle="Applies the next time the monitor is started">
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Interface backend" hint="'virtual' needs no hardware">
            {(id, describedBy) => (
              <Select
                id={id}
                aria-describedby={describedBy}
                value={draft.can_interface}
                onChange={(event) => set('can_interface', event.target.value)}
              >
                <option value="virtual">virtual (simulator)</option>
                <option value="python-can">python-can (hardware)</option>
                <option value="mock">mock (testing)</option>
              </Select>
            )}
          </Field>
          <Field label="Channel" hint="e.g. vcan0, can0, COM3">
            {(id, describedBy) => (
              <TextInput
                id={id}
                aria-describedby={describedBy}
                value={draft.can_channel}
                onChange={(event) => set('can_channel', event.target.value)}
              />
            )}
          </Field>
          {numberField('can_bitrate', 'Bitrate (bit/s)', 'Typically 500000 for a powertrain bus.', '1000')}
        </div>
      </Panel>

      <Panel title="Retention" subtitle="Bounds on how much history is kept">
        <div className="grid gap-3 sm:grid-cols-2">
          <Toggle
            checked={draft.retention_enabled}
            onChange={(value) => set('retention_enabled', value)}
            label="Retention enabled"
            description="Periodically prune old rows so the database cannot grow without limit."
          />
          <Toggle
            checked={draft.persist_can_messages}
            onChange={(value) => set('persist_can_messages', value)}
            label="Record every CAN frame"
            description="Turn off to store only security events — useful under sustained high load."
          />
        </div>
        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          {numberField('max_messages', 'Max stored frames', 'Oldest frames are pruned beyond this.', '1000')}
          {numberField('max_security_events', 'Max stored events', 'Oldest events are pruned beyond this.', '100')}
          {numberField('max_age_days', 'Max age (days)', 'Rows older than this are removed.', '1')}
        </div>
      </Panel>
    </div>
  )
}
