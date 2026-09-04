import { Filter, Pause, Play, Radio, Trash2 } from 'lucide-react'
import { useDeferredValue, useMemo, useRef, useState } from 'react'
import { TrafficTable } from '@/components/traffic/TrafficTable'
import { Pill, StatusBadge } from '@/components/ui/Badge'
import { Button, Field, Select, TextInput, Toggle } from '@/components/ui/Controls'
import { Panel } from '@/components/ui/Panel'
import { StatCard } from '@/components/ui/StatCard'
import { useLiveStatus, useLiveTraffic } from '@/hooks/liveData'
import { formatCompact, formatRate } from '@/utils/format'
import type { CanMessage } from '@/types/api'

type SortKey = 'time' | 'can_id' | 'dlc'

/** Frames rendered at once. Enough to fill any screen, few enough to stay smooth. */
const RENDER_LIMIT = 150

export function TrafficPage() {
  const { messages, observedInLastFlush, sampled, totalReceived, clear } = useLiveTraffic()
  const { monitorStatus, currentRate, systemStatus } = useLiveStatus()

  const [paused, setPaused] = useState(false)
  const [search, setSearch] = useState('')
  const [canIdFilter, setCanIdFilter] = useState('')
  const [flaggedOnly, setFlaggedOnly] = useState(false)
  const [sortKey, setSortKey] = useState<SortKey>('time')
  const openedAt = useRef(Date.now() / 1000)

  // Deferring the text filters keeps typing responsive while frames stream in.
  const deferredSearch = useDeferredValue(search)
  const deferredCanId = useDeferredValue(canIdFilter)

  // Snapshot the buffer when paused, so the operator can read a specific frame.
  const frozen = useRef<CanMessage[]>([])
  if (!paused) frozen.current = messages
  const source = paused ? frozen.current : messages

  const knownIds = useMemo(() => {
    const ids = new Map<string, string>()
    for (const message of source) {
      if (!ids.has(message.can_id_hex)) ids.set(message.can_id_hex, message.label ?? '')
    }
    return [...ids.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  }, [source])

  const filtered = useMemo(() => {
    const needle = deferredSearch.trim().toUpperCase()
    let rows = source.filter((message) => {
      if (flaggedOnly && !message.flagged) return false
      if (deferredCanId && message.can_id_hex !== deferredCanId) return false
      if (!needle) return true
      return (
        message.data.includes(needle) ||
        // can_id_hex is written "0x300", so it must be folded to match an
        // uppercased needle like "0X300".
        message.can_id_hex.toUpperCase().includes(needle) ||
        (message.label ?? '').toUpperCase().includes(needle) ||
        message.source.includes(needle)
      )
    })

    rows = [...rows].reverse() // newest first
    if (sortKey === 'can_id') {
      rows.sort((a, b) => a.can_id - b.can_id || b.timestamp - a.timestamp)
    } else if (sortKey === 'dlc') {
      rows.sort((a, b) => b.dlc - a.dlc || b.timestamp - a.timestamp)
    }
    return rows.slice(0, RENDER_LIMIT)
  }, [source, deferredSearch, deferredCanId, flaggedOnly, sortKey])

  const flaggedCount = useMemo(() => source.filter((message) => message.flagged).length, [source])

  return (
    <div className="space-y-4">
      <section aria-label="Traffic overview" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Current rate"
          value={formatRate(currentRate)}
          unit="msg/s"
          icon={<Radio className="h-4 w-4" />}
          tone="accent"
          hint={`Buffered ${source.length} frames`}
        />
        <StatCard
          label="Frames streamed"
          value={formatCompact(totalReceived)}
          hint={sampled ? `Sampled: ${observedInLastFlush} observed last flush` : 'Full stream'}
        />
        <StatCard
          label="Flagged in buffer"
          value={formatCompact(flaggedCount)}
          tone={flaggedCount > 0 ? 'warn' : 'neutral'}
          hint="Frames a detector marked"
        />
        <StatCard
          label="Interface"
          value={monitorStatus?.interface?.channel ?? '—'}
          hint={
            monitorStatus?.interface
              ? `${monitorStatus.interface.backend} · dropped ${monitorStatus.interface.statistics.dropped}`
              : 'Monitor stopped'
          }
          tone={monitorStatus?.running ? 'ok' : 'neutral'}
        />
      </section>

      <Panel
        title="Live CAN trace"
        subtitle={
          sampled
            ? 'The stream is sampled while the bus is saturated; counters remain exact.'
            : 'Every frame received by the monitor, newest first.'
        }
        icon={<Filter className="h-4 w-4" />}
        flush
        actions={
          <>
            <StatusBadge
              kind={paused ? 'warn' : monitorStatus?.running ? 'ok' : 'idle'}
              label={paused ? 'Paused' : monitorStatus?.running ? 'Live' : 'Idle'}
              live={!paused && monitorStatus?.running}
            />
            <Button
              size="sm"
              onClick={() => setPaused((value) => !value)}
              icon={paused ? <Play className="h-3 w-3" /> : <Pause className="h-3 w-3" />}
            >
              {paused ? 'Resume' : 'Pause'}
            </Button>
            <Button size="sm" variant="ghost" onClick={clear} icon={<Trash2 className="h-3 w-3" />}>
              Clear
            </Button>
          </>
        }
      >
        <div className="grid gap-3 border-b border-base-700/70 p-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Search" hint="Payload bytes, identifier, signal name or source">
            {(id, describedBy) => (
              <TextInput
                id={id}
                aria-describedby={describedBy}
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="e.g. 0x300, DEADBEEF, speed"
              />
            )}
          </Field>

          <Field label="CAN identifier" hint={`${knownIds.length} identifiers in the buffer`}>
            {(id, describedBy) => (
              <Select
                id={id}
                aria-describedby={describedBy}
                value={canIdFilter}
                onChange={(event) => setCanIdFilter(event.target.value)}
              >
                <option value="">All identifiers</option>
                {knownIds.map(([hex, label]) => (
                  <option key={hex} value={hex}>
                    {hex}
                    {label ? ` — ${label}` : ''}
                  </option>
                ))}
              </Select>
            )}
          </Field>

          <Field label="Sort by" hint="Time keeps the newest frame at the top">
            {(id, describedBy) => (
              <Select
                id={id}
                aria-describedby={describedBy}
                value={sortKey}
                onChange={(event) => setSortKey(event.target.value as SortKey)}
              >
                <option value="time">Time (newest first)</option>
                <option value="can_id">CAN identifier</option>
                <option value="dlc">Payload length</option>
              </Select>
            )}
          </Field>

          <div className="flex items-end">
            <Toggle
              checked={flaggedOnly}
              onChange={setFlaggedOnly}
              label="Attacks only"
              description="Show just the frames a detector flagged"
            />
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 border-b border-base-700/70 px-4 py-2 text-2xs text-ink-faint">
          <Pill>{filtered.length} shown</Pill>
          <Pill>{source.length} in buffer</Pill>
          {systemStatus && <Pill>flush {systemStatus.websocket.flush_interval_ms} ms</Pill>}
          {filtered.length === RENDER_LIMIT && (
            <span>Showing the newest {RENDER_LIMIT}. Narrow the filter to see more.</span>
          )}
        </div>

        <TrafficTable
          messages={filtered}
          highlightAfter={openedAt.current}
          maxHeight="34rem"
          emptyTitle={source.length === 0 ? 'Waiting for CAN frames' : 'No frames match the filter'}
          emptyDescription={
            source.length === 0
              ? 'Start the monitor and the simulator to generate traffic.'
              : 'Clear the search or identifier filter to see more frames.'
          }
        />
      </Panel>
    </div>
  )
}
