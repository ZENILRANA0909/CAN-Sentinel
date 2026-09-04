import {
  Activity,
  Car,
  Play,
  RotateCcw,
  Send,
  Square,
  Zap,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { TrafficChart } from '@/components/charts/TrafficChart'
import { Pill, StatusBadge } from '@/components/ui/Badge'
import { Button, Field, Segmented, TextInput } from '@/components/ui/Controls'
import { Panel } from '@/components/ui/Panel'
import { StatCard } from '@/components/ui/StatCard'
import { LoadingState } from '@/components/ui/States'
import { useLiveStatus } from '@/hooks/liveData'
import { usePolledResource } from '@/hooks/usePolledResource'
import { useRateSeries } from '@/hooks/useRateSeries'
import { ApiRequestError, api, type SimulationRequestBody } from '@/services/api'
import { formatCompact, formatDuration, formatRate } from '@/utils/format'
import type { SimulationMode } from '@/types/api'

const MODE_OPTIONS: Array<{ value: SimulationMode; label: string; tone?: 'default' | 'danger' }> = [
  { value: 'NORMAL', label: 'Normal' },
  { value: 'FAKE_SPEED', label: 'Fake Speed', tone: 'danger' },
  { value: 'CAN_FLOOD', label: 'CAN Flood', tone: 'danger' },
  { value: 'MIXED', label: 'Mixed', tone: 'danger' },
  { value: 'CUSTOM', label: 'Custom' },
]

const MODE_HELP: Record<SimulationMode, string> = {
  NORMAL:
    'A realistic vehicle bus: engine, speed, brake, steering and transmission frames at their normal periods.',
  FAKE_SPEED:
    'Injects forged speed frames alongside the genuine ones. Expect FAKE_SPEED, and a frequency anomaly on 0x300 because the identifier now transmits faster than its baseline.',
  CAN_FLOOD:
    'Floods the bus with high-priority frames. Expect CAN_FLOOD, plus an ID anomaly because the flood identifier is not in the allowlist.',
  MIXED: 'Runs the speed spoof and the flood together — several detectors fire at once.',
  CUSTOM: 'Normal traffic plus the frames you define below, on the interval you choose.',
}

interface CustomFrameDraft {
  can_id: string
  data: string
  interval_ms: string
}

export function SimulatorPage() {
  const { simulationStatus, monitorStatus, currentRate, attacksTotal } = useLiveStatus()
  const { series, floodThreshold, suspiciousThreshold } = useRateSeries(120)

  const status = usePolledResource(() => api.simulationStatus(), [], { intervalMs: 4_000 })
  const live = simulationStatus ?? status.data

  const [mode, setMode] = useState<SimulationMode>('NORMAL')
  const [floodRate, setFloodRate] = useState('1200')
  const [fakeSpeed, setFakeSpeed] = useState('255')
  const [fakeSpeedRate, setFakeSpeedRate] = useState('100')
  const [custom, setCustom] = useState<CustomFrameDraft>({
    can_id: '0x123',
    data: 'DEADBEEF',
    interval_ms: '100',
  })
  const [injectFrame, setInjectFrame] = useState({ can_id: '0x1A5', data: 'AABBCCDD' })

  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  // Adopt the backend's mode so the controls reflect reality after a reload.
  useEffect(() => {
    if (live?.mode) setMode(live.mode)
  }, [live?.mode])

  const buildBody = useCallback((): SimulationRequestBody => {
    const body: SimulationRequestBody = { mode }
    if (mode === 'CAN_FLOOD' || mode === 'MIXED') {
      const rate = Number(floodRate)
      if (Number.isFinite(rate) && rate > 0) body.flood_rate = rate
    }
    if (mode === 'FAKE_SPEED' || mode === 'MIXED') {
      const value = Number(fakeSpeed)
      const rate = Number(fakeSpeedRate)
      if (Number.isFinite(value) && value >= 0) body.fake_speed_value = value
      if (Number.isFinite(rate) && rate > 0) body.fake_speed_rate = rate
    }
    if (mode === 'CUSTOM') {
      const canId = custom.can_id.trim().toLowerCase()
      body.custom_frames = [
        {
          can_id: canId.startsWith('0x') ? parseInt(canId, 16) : Number(canId),
          data: custom.data.trim(),
          interval_ms: Number(custom.interval_ms) || 100,
        },
      ]
    }
    return body
  }, [mode, floodRate, fakeSpeed, fakeSpeedRate, custom])

  const run = useCallback(
    async (action: string, work: () => Promise<unknown>, successMessage: string) => {
      setBusy(action)
      setError(null)
      setNotice(null)
      try {
        await work()
        setNotice(successMessage)
        await status.refetch()
      } catch (caught) {
        setError(
          caught instanceof ApiRequestError ? caught.message : 'The control action failed.',
        )
      } finally {
        setBusy(null)
      }
    },
    [status],
  )

  const running = live?.running ?? false
  const vehicle = live?.vehicle

  return (
    <div className="space-y-4">
      <section aria-label="Simulator overview" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Simulator"
          value={running ? 'RUNNING' : 'STOPPED'}
          tone={running ? (live?.attack_active ? 'bad' : 'ok') : 'neutral'}
          icon={<Activity className="h-4 w-4" />}
          hint={live ? `${live.mode_label} · ${formatDuration(live.uptime_seconds)}` : '—'}
        />
        <StatCard
          label="Generated rate"
          value={formatRate(live?.generated_rate_msg_per_s ?? 0)}
          unit="msg/s"
          tone="accent"
          hint={`Observed on the bus: ${formatRate(currentRate)} msg/s`}
        />
        <StatCard
          label="Frames generated"
          value={formatCompact(live?.messages_generated ?? 0)}
          hint={`${formatCompact(live?.attack_messages ?? 0)} attack frames`}
          tone={(live?.attack_messages ?? 0) > 0 ? 'warn' : 'neutral'}
        />
        <StatCard
          label="Attacks detected"
          value={formatCompact(attacksTotal)}
          tone={attacksTotal > 0 ? 'warn' : 'neutral'}
          icon={<Zap className="h-4 w-4" />}
          hint="Confirmed by the detection engine"
        />
      </section>

      <div className="grid gap-4 xl:grid-cols-3">
        <Panel
          className="xl:col-span-2"
          title="Simulation control"
          subtitle="Generate normal vehicle traffic, or run an attack against it"
          icon={<Activity className="h-4 w-4" />}
          actions={
            <StatusBadge
              kind={running ? (live?.attack_active ? 'bad' : 'ok') : 'idle'}
              label={running ? (live?.attack_active ? 'Attack running' : 'Generating') : 'Stopped'}
              live={running}
            />
          }
        >
          <Segmented
            ariaLabel="Simulation mode"
            options={MODE_OPTIONS}
            value={mode}
            onChange={setMode}
          />
          <p className="mt-2.5 text-xs leading-relaxed text-ink-muted">{MODE_HELP[mode]}</p>

          {(mode === 'CAN_FLOOD' || mode === 'MIXED') && (
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <Field
                label="Flood rate"
                hint={`Frames per second injected. Detector threshold: ${formatRate(floodThreshold)} msg/s.`}
              >
                {(id, describedBy) => (
                  <TextInput
                    id={id}
                    aria-describedby={describedBy}
                    type="number"
                    min={1}
                    max={20000}
                    value={floodRate}
                    onChange={(event) => setFloodRate(event.target.value)}
                  />
                )}
              </Field>
            </div>
          )}

          {(mode === 'FAKE_SPEED' || mode === 'MIXED') && (
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <Field label="Spoofed speed (km/h)" hint="Value written into the forged speed frames">
                {(id, describedBy) => (
                  <TextInput
                    id={id}
                    aria-describedby={describedBy}
                    type="number"
                    min={0}
                    max={655}
                    value={fakeSpeed}
                    onChange={(event) => setFakeSpeed(event.target.value)}
                  />
                )}
              </Field>
              <Field label="Injection rate (frames/s)" hint="The genuine ECU keeps sending at 50 Hz">
                {(id, describedBy) => (
                  <TextInput
                    id={id}
                    aria-describedby={describedBy}
                    type="number"
                    min={1}
                    max={5000}
                    value={fakeSpeedRate}
                    onChange={(event) => setFakeSpeedRate(event.target.value)}
                  />
                )}
              </Field>
            </div>
          )}

          {mode === 'CUSTOM' && (
            <div className="mt-3 grid gap-3 sm:grid-cols-3">
              <Field label="CAN identifier" hint="Decimal or 0x-prefixed hex">
                {(id, describedBy) => (
                  <TextInput
                    id={id}
                    aria-describedby={describedBy}
                    value={custom.can_id}
                    onChange={(event) => setCustom({ ...custom, can_id: event.target.value })}
                  />
                )}
              </Field>
              <Field label="Payload (hex)" hint="Up to 8 bytes">
                {(id, describedBy) => (
                  <TextInput
                    id={id}
                    aria-describedby={describedBy}
                    value={custom.data}
                    onChange={(event) => setCustom({ ...custom, data: event.target.value })}
                  />
                )}
              </Field>
              <Field label="Interval (ms)">
                {(id) => (
                  <TextInput
                    id={id}
                    type="number"
                    min={1}
                    value={custom.interval_ms}
                    onChange={(event) => setCustom({ ...custom, interval_ms: event.target.value })}
                  />
                )}
              </Field>
            </div>
          )}

          <div className="mt-4 flex flex-wrap gap-2">
            <Button
              variant="primary"
              loading={busy === 'start'}
              disabled={running}
              icon={<Play className="h-3.5 w-3.5" />}
              onClick={() =>
                run('start', () => api.startSimulation(buildBody()), 'Simulation started.')
              }
            >
              Start
            </Button>
            <Button
              loading={busy === 'apply'}
              disabled={!running}
              icon={<Zap className="h-3.5 w-3.5" />}
              onClick={() =>
                run('apply', () => api.setSimulationMode(buildBody()), `Switched to ${mode} mode.`)
              }
            >
              Apply mode
            </Button>
            <Button
              variant="danger"
              loading={busy === 'stop'}
              disabled={!running}
              icon={<Square className="h-3.5 w-3.5" />}
              onClick={() => run('stop', () => api.stopSimulation(), 'Simulation stopped.')}
            >
              Stop
            </Button>
            <Button
              variant="ghost"
              loading={busy === 'reset'}
              icon={<RotateCcw className="h-3.5 w-3.5" />}
              onClick={() =>
                run('reset', () => api.resetSimulation(), 'Vehicle model and live counters reset.')
              }
            >
              Reset
            </Button>
          </div>

          {!monitorStatus?.running && (
            <p className="mt-3 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-2xs text-amber-200">
              The monitor is stopped. Starting the simulation will start it automatically so the
              generated frames have a bus to travel on.
            </p>
          )}
          {error && (
            <p role="alert" className="mt-3 rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-200">
              {error}
            </p>
          )}
          {notice && !error && (
            <p role="status" className="mt-3 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200">
              {notice}
            </p>
          )}
        </Panel>

        <Panel
          title="Vehicle state"
          subtitle="The model driving the simulated bus"
          icon={<Car className="h-4 w-4" />}
        >
          {vehicle ? (
            <dl className="space-y-2 text-xs">
              {[
                ['Drive phase', vehicle.phase],
                ['Speed', `${vehicle.speed_kmh} km/h`],
                ['Engine', `${vehicle.engine_rpm} rpm`],
                ['Gear', String(vehicle.gear)],
                ['Throttle', `${vehicle.throttle_pct} %`],
                ['Brake', vehicle.brake_pressed ? `${vehicle.brake_pedal_pct} %` : 'released'],
                ['Coolant', `${vehicle.coolant_temp_c} °C`],
                ['Fuel', `${vehicle.fuel_level_pct} %`],
                ['Steering', `${vehicle.steering_angle_deg}°`],
                ['Odometer', `${vehicle.odometer_km} km`],
              ].map(([label, value]) => (
                <div key={label} className="flex items-center justify-between gap-3">
                  <dt className="text-ink-faint">{label}</dt>
                  <dd className="mono text-ink">{value}</dd>
                </div>
              ))}
            </dl>
          ) : status.loading ? (
            <LoadingState label="Loading vehicle state…" />
          ) : (
            <p className="py-6 text-center text-xs text-ink-muted">
              Start the simulator to see the vehicle model.
            </p>
          )}
        </Panel>
      </div>

      <Panel
        title="Generated load"
        subtitle="What the simulator is putting on the bus, against the detector thresholds"
      >
        <TrafficChart
          data={series}
          floodThreshold={floodThreshold}
          suspiciousThreshold={suspiciousThreshold}
          height={220}
        />
      </Panel>

      <Panel
        title="Inject a single frame"
        subtitle="Transmit one arbitrary frame — the quickest way to demonstrate the identifier-anomaly detector"
        icon={<Send className="h-4 w-4" />}
      >
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="CAN identifier" hint="An identifier outside the allowlist triggers ID_ANOMALY">
            {(id, describedBy) => (
              <TextInput
                id={id}
                aria-describedby={describedBy}
                value={injectFrame.can_id}
                onChange={(event) => setInjectFrame({ ...injectFrame, can_id: event.target.value })}
              />
            )}
          </Field>
          <Field label="Payload (hex)" hint="Up to 8 bytes, e.g. AABBCCDD">
            {(id, describedBy) => (
              <TextInput
                id={id}
                aria-describedby={describedBy}
                value={injectFrame.data}
                onChange={(event) => setInjectFrame({ ...injectFrame, data: event.target.value })}
              />
            )}
          </Field>
          <div className="flex items-end">
            <Button
              variant="primary"
              className="w-full"
              loading={busy === 'inject'}
              icon={<Send className="h-3.5 w-3.5" />}
              onClick={() => {
                const raw = injectFrame.can_id.trim().toLowerCase()
                const canId = raw.startsWith('0x') ? parseInt(raw, 16) : Number(raw)
                return run(
                  'inject',
                  () => api.injectFrame({ can_id: canId, data: injectFrame.data.trim() }),
                  `Frame ${injectFrame.can_id} transmitted.`,
                )
              }}
            >
              Inject frame
            </Button>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <Pill>Allowlisted: 0x100 · 0x200 · 0x300 · 0x400 · 0x500 · 0x600 · 0x700</Pill>
          <Pill>Anything else is reported as an identifier anomaly</Pill>
        </div>
      </Panel>
    </div>
  )
}
