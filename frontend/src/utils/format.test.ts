import { describe, expect, it } from 'vitest'
import {
  attackColor,
  attackLabel,
  detectorLabel,
  formatBytes,
  formatCanId,
  formatCompact,
  formatDuration,
  formatNumber,
  formatPayload,
  formatPercent,
  formatRate,
  humanizeSignal,
  severityTone,
  threatTone,
} from './format'

describe('numeric formatting', () => {
  it('formats integers and fractions', () => {
    expect(formatNumber(1234)).toBe('1,234')
    expect(formatNumber(12.345, 2)).toBe('12.35')
  })

  it('renders an em dash for missing values', () => {
    for (const value of [null, undefined, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(formatNumber(value)).toBe('—')
      expect(formatRate(value)).toBe('—')
      expect(formatBytes(value)).toBe('—')
      expect(formatCompact(value)).toBe('—')
    }
  })

  it('abbreviates only large counters', () => {
    // Below the threshold the value is shown in full.
    expect(formatCompact(9999)).toBe('9,999')
    // Above it, Intl compact notation applies. The exact form is locale
    // dependent (1.5M in en-US, 15L in en-IN), so assert the contract - a
    // materially shorter string - rather than one locale's spelling.
    const compact = formatCompact(1_500_000)
    expect(compact.length).toBeLessThan(formatNumber(1_500_000).length)
    expect(compact).not.toContain('500,000')
  })

  it('keeps a decimal for low rates and drops it for high ones', () => {
    expect(formatRate(12.34)).toBe('12.3')
    expect(formatRate(1234)).toBe('1,234')
  })

  it('scales byte counts', () => {
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(2048)).toBe('2.0 KB')
    expect(formatBytes(5 * 1024 * 1024)).toBe('5.0 MB')
  })

  it('formats confidence as a percentage', () => {
    expect(formatPercent(0.935)).toBe('94%')
    expect(formatPercent(0.5, 1)).toBe('50.0%')
  })
})

describe('duration formatting', () => {
  it.each([
    [0, '0s'],
    [45, '45s'],
    [90, '1m 30s'],
    [3661, '1h 1m 1s'],
    [90_061, '1d 1h 1m'],
  ])('formats %i seconds as %s', (seconds, expected) => {
    expect(formatDuration(seconds)).toBe(expected)
  })

  it('rejects negative and missing durations', () => {
    expect(formatDuration(-1)).toBe('—')
    expect(formatDuration(null)).toBe('—')
  })
})

describe('CAN formatting', () => {
  it('pads standard and extended identifiers differently', () => {
    expect(formatCanId(0x300)).toBe('0x300')
    expect(formatCanId(0)).toBe('0x000')
    expect(formatCanId(0x18daf110, true)).toBe('0x18DAF110')
    expect(formatCanId(null)).toBe('—')
  })

  it('groups payload bytes into readable pairs', () => {
    expect(formatPayload('DEADBEEF')).toBe('DE AD BE EF')
    expect(formatPayload('')).toBe('—')
    expect(formatPayload(null)).toBe('—')
  })

  it('turns signal keys into readable labels with units', () => {
    expect(humanizeSignal('vehicle_speed_kmh')).toBe('Vehicle speed (km/h)')
    expect(humanizeSignal('engine_load_pct')).toBe('Engine load (%)')
    expect(humanizeSignal('coolant_temp_c')).toBe('Coolant temp (°C)')
    expect(humanizeSignal('brake_pressed')).toBe('Brake pressed')
  })
})

describe('domain vocabulary', () => {
  it('maps every severity to a distinct tone', () => {
    const hexes = (['INFO', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'] as const).map(
      (level) => severityTone(level).hex,
    )
    expect(new Set(hexes).size).toBe(5)
  })

  it('falls back safely for an unknown severity', () => {
    expect(severityTone('NONSENSE').label).toBe('Info')
    expect(severityTone(null).label).toBe('Info')
  })

  it('maps threat levels', () => {
    expect(threatTone('NORMAL').label).toBe('Normal')
    expect(threatTone('ATTACK').label).toBe('Under attack')
    expect(threatTone(undefined).label).toBe('Normal')
  })

  it('labels attack types for display', () => {
    expect(attackLabel('FAKE_SPEED')).toBe('Fake Speed')
    expect(attackLabel('CAN_FLOOD')).toBe('CAN Flood')
    expect(attackLabel('SOMETHING_NEW')).toBe('SOMETHING_NEW')
  })

  it('gives each attack type its own colour', () => {
    const colors = ['FAKE_SPEED', 'CAN_FLOOD', 'ID_ANOMALY', 'FREQUENCY_ANOMALY'].map(attackColor)
    expect(new Set(colors).size).toBe(4)
    expect(attackColor('UNKNOWN')).toBe('#64748b')
  })

  it('humanises detector names', () => {
    expect(detectorLabel('fake_speed')).toBe('Fake Speed')
    expect(detectorLabel('frequency_anomaly')).toBe('Frequency Anomaly')
  })
})
