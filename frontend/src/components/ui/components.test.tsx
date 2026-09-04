import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ApiRequestError } from '@/services/api'
import { Pill, SeverityBadge, StatusBadge, ThreatBadge } from './Badge'
import { Button, Segmented, Toggle } from './Controls'
import { Panel } from './Panel'
import { StatCard } from './StatCard'
import { EmptyState, ErrorState, LoadingState } from './States'
import { AttackAlert } from '@/components/security/AttackAlert'
import { TrafficTable } from '@/components/traffic/TrafficTable'
import type { CanMessage, SecurityEvent } from '@/types/api'

describe('badges', () => {
  it('names the severity rather than relying on colour alone', () => {
    render(<SeverityBadge severity="CRITICAL" />)
    expect(screen.getByText('Critical')).toBeInTheDocument()
  })

  it('names the threat level', () => {
    render(<ThreatBadge level="ATTACK" />)
    expect(screen.getByText('Under attack')).toBeInTheDocument()
  })

  it('renders a status label next to its dot', () => {
    render(<StatusBadge kind="ok" label="System online" live />)
    expect(screen.getByText('System online')).toBeInTheDocument()
  })

  it('renders a pill', () => {
    render(<Pill>NORMAL</Pill>)
    expect(screen.getByText('NORMAL')).toBeInTheDocument()
  })
})

describe('StatCard', () => {
  it('shows the label, value, unit and hint', () => {
    render(<StatCard label="Messages / sec" value="284" unit="msg/s" hint="Peak 1,490" />)
    expect(screen.getByText('Messages / sec')).toBeInTheDocument()
    expect(screen.getByText('284')).toBeInTheDocument()
    expect(screen.getByText('msg/s')).toBeInTheDocument()
    expect(screen.getByText('Peak 1,490')).toBeInTheDocument()
  })
})

describe('Panel', () => {
  it('renders its heading as a real heading element', () => {
    render(
      <Panel title="Bus load" subtitle="Messages per second">
        <p>content</p>
      </Panel>,
    )
    expect(screen.getByRole('heading', { name: 'Bus load' })).toBeInTheDocument()
    expect(screen.getByText('content')).toBeInTheDocument()
  })
})

describe('state components', () => {
  it('announces loading politely', () => {
    render(<LoadingState label="Loading events…" />)
    expect(screen.getByRole('status')).toHaveTextContent('Loading events…')
  })

  it('renders an empty state with an explanation', () => {
    render(<EmptyState title="No attacks detected" description="The bus is clean." />)
    expect(screen.getByText('No attacks detected')).toBeInTheDocument()
    expect(screen.getByText('The bus is clean.')).toBeInTheDocument()
  })

  it('distinguishes an offline backend from a generic error', () => {
    const { rerender } = render(
      <ErrorState error={new ApiRequestError('Cannot reach the backend.', 0, 'network_error')} />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('Backend unreachable')

    rerender(<ErrorState error={new ApiRequestError('Boom', 500, 'internal_error')} />)
    expect(screen.getByRole('alert')).toHaveTextContent('Could not load this view')
  })

  it('offers a retry action', async () => {
    const onRetry = vi.fn()
    render(<ErrorState error="broken" onRetry={onRetry} />)
    await userEvent.click(screen.getByRole('button', { name: /retry/i }))
    expect(onRetry).toHaveBeenCalledOnce()
  })
})

describe('controls', () => {
  it('disables a button while loading', () => {
    render(<Button loading>Start</Button>)
    expect(screen.getByRole('button', { name: 'Start' })).toBeDisabled()
  })

  it('exposes a toggle as a switch', async () => {
    const onChange = vi.fn()
    render(<Toggle checked={false} onChange={onChange} label="Attacks only" />)
    const toggle = screen.getByRole('switch', { name: /attacks only/i })
    await userEvent.click(toggle)
    expect(onChange).toHaveBeenCalledWith(true)
  })

  it('exposes segmented options as a radio group', async () => {
    const onChange = vi.fn()
    render(
      <Segmented
        ariaLabel="Simulation mode"
        value="NORMAL"
        onChange={onChange}
        options={[
          { value: 'NORMAL', label: 'Normal' },
          { value: 'CAN_FLOOD', label: 'CAN Flood', tone: 'danger' },
        ]}
      />,
    )
    const group = screen.getByRole('radiogroup', { name: 'Simulation mode' })
    expect(group).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: 'Normal' })).toHaveAttribute('aria-checked', 'true')

    await userEvent.click(screen.getByRole('radio', { name: 'CAN Flood' }))
    expect(onChange).toHaveBeenCalledWith('CAN_FLOOD')
  })
})

const EVENT: SecurityEvent = {
  id: 7,
  timestamp: 1735900000,
  iso_timestamp: '2025-01-03T12:00:00+00:00',
  attack_type: 'FAKE_SPEED',
  threat_level: 'ATTACK',
  severity: 'HIGH',
  detector: 'fake_speed',
  can_id: 0x300,
  can_id_hex: '0x300',
  confidence: 0.93,
  description: 'Forged vehicle speed: 255.0 km/h reported on 0x300',
  evidence: { observed_speed_kmh: 255, attack_threshold_kmh: 200, rule: 'speed_above_threshold' },
  status: 'NEW',
}

describe('AttackAlert', () => {
  it('summarises the verdict', () => {
    render(<AttackAlert event={EVENT} />)
    expect(screen.getByText('Fake Speed')).toBeInTheDocument()
    expect(screen.getByText('High')).toBeInTheDocument()
    expect(screen.getByText('0x300')).toBeInTheDocument()
    expect(screen.getByText(EVENT.description)).toBeInTheDocument()
    expect(screen.getByText('93%')).toBeInTheDocument()
  })

  it('keeps the evidence collapsed until asked for', async () => {
    render(<AttackAlert event={EVENT} />)
    expect(screen.queryByText('Observed speed (km/h)')).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /show evidence/i }))
    expect(screen.getByText('Observed speed (km/h)')).toBeInTheDocument()
    expect(screen.getByText('255')).toBeInTheDocument()
  })

  it('can start expanded', () => {
    render(<AttackAlert event={EVENT} defaultExpanded />)
    expect(screen.getByText('Attack threshold (km/h)')).toBeInTheDocument()
  })
})

const FRAME: CanMessage = {
  timestamp: 1735900000.5,
  iso_timestamp: '2025-01-03T12:00:00.5+00:00',
  can_id: 0x300,
  can_id_hex: '0x300',
  is_extended_id: false,
  dlc: 8,
  data: '17700000010000A5',
  channel: 'vcan0',
  direction: 'RX',
  source: 'SIMULATOR',
  message_type: 'DATA',
  flagged: false,
  label: 'Vehicle Speed',
  decoded: { vehicle_speed_kmh: 60 },
  attack_types: [],
}

describe('TrafficTable', () => {
  it('shows an empty state when there are no frames', () => {
    render(<TrafficTable messages={[]} />)
    expect(screen.getByText(/no frames match/i)).toBeInTheDocument()
  })

  it('renders a frame as an accessible table row', () => {
    render(<TrafficTable messages={[FRAME]} />)
    expect(screen.getByRole('table')).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'CAN ID' })).toBeInTheDocument()
    expect(screen.getByText('0x300')).toBeInTheDocument()
    expect(screen.getByText('17 70 00 00 01 00 00 A5')).toBeInTheDocument()
    expect(screen.getByText(/Vehicle speed \(km\/h\): 60/)).toBeInTheDocument()
    expect(screen.getByText('Normal')).toBeInTheDocument()
  })

  it('marks a flagged frame with its attack type', () => {
    render(
      <TrafficTable
        messages={[{ ...FRAME, flagged: true, severity: 'HIGH', attack_types: ['FAKE_SPEED'] }]}
      />,
    )
    expect(screen.getByLabelText('Flagged by a detector')).toBeInTheDocument()
    expect(screen.getByText('Fake Speed')).toBeInTheDocument()
  })
})
