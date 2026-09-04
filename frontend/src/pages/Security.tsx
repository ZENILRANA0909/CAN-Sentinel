import { CheckCircle2, RefreshCw, ShieldAlert, ShieldCheck } from 'lucide-react'
import { useCallback, useState } from 'react'
import { AttackAlert } from '@/components/security/AttackAlert'
import { Pill, StatusBadge, ThreatBadge } from '@/components/ui/Badge'
import { Button, Field, Select } from '@/components/ui/Controls'
import { Panel } from '@/components/ui/Panel'
import { StatCard } from '@/components/ui/StatCard'
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/States'
import { useLiveStatus } from '@/hooks/liveData'
import { usePolledResource } from '@/hooks/usePolledResource'
import { ApiRequestError, api } from '@/services/api'
import { SEVERITY_ORDER, attackLabel, formatCompact } from '@/utils/format'
import type { AttackType, EventStatus, Severity } from '@/types/api'

const ATTACK_TYPES: AttackType[] = ['FAKE_SPEED', 'CAN_FLOOD', 'ID_ANOMALY', 'FREQUENCY_ANOMALY']
const STATUSES: EventStatus[] = ['NEW', 'ACKNOWLEDGED', 'RESOLVED']
const PAGE_SIZE = 25

export function SecurityPage() {
  const { threatLevel, activeAlerts, attacksTotal, alertPulse } = useLiveStatus()

  const [attackType, setAttackType] = useState<AttackType | ''>('')
  const [severity, setSeverity] = useState<Severity | ''>('')
  const [status, setStatus] = useState<EventStatus | ''>('')
  const [page, setPage] = useState(0)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const events = usePolledResource(
    () =>
      api.attacks({
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
        attack_type: attackType || undefined,
        severity: severity || undefined,
        status: status || undefined,
      }),
    // `alertPulse` changes on every new alert, which refreshes page 1 promptly.
    [attackType, severity, status, page, page === 0 ? alertPulse : 0],
    { intervalMs: 8_000 },
  )

  const triage = useCallback(
    async (eventId: number, next: EventStatus) => {
      setBusyId(eventId)
      setActionError(null)
      try {
        await api.updateAttackStatus(eventId, next)
        await events.refetch()
      } catch (error) {
        setActionError(
          error instanceof ApiRequestError ? error.message : 'Could not update the event status.',
        )
      } finally {
        setBusyId(null)
      }
    },
    [events],
  )

  const resetFilters = () => {
    setAttackType('')
    setSeverity('')
    setStatus('')
    setPage(0)
  }

  const items = events.data?.items ?? []
  const total = events.data?.total ?? 0
  const hasFilters = Boolean(attackType || severity || status)

  return (
    <div className="space-y-4">
      <section aria-label="Security posture" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Threat level"
          value={threatLevel}
          icon={<ShieldAlert className="h-4 w-4" />}
          tone={threatLevel === 'ATTACK' ? 'bad' : threatLevel === 'SUSPICIOUS' ? 'warn' : 'ok'}
          hint="Derived from alerts in the recent window"
        />
        <StatCard
          label="Active alerts"
          value={formatCompact(activeAlerts)}
          tone={activeAlerts > 0 ? 'warn' : 'ok'}
          hint="Alerts still inside the active window"
        />
        <StatCard label="Detected this session" value={formatCompact(attacksTotal)} />
        <StatCard
          label="Stored events"
          value={formatCompact(total)}
          hint={hasFilters ? 'Matching the current filter' : 'All recorded events'}
        />
      </section>

      <Panel
        title="Security events"
        subtitle="Every detection the engine persisted, with its supporting evidence"
        icon={<ShieldAlert className="h-4 w-4" />}
        actions={
          <>
            <ThreatBadge level={threatLevel} />
            <StatusBadge
              kind={events.refreshing ? 'busy' : 'ok'}
              label={events.refreshing ? 'Refreshing' : 'Up to date'}
            />
            <Button
              size="sm"
              variant="ghost"
              onClick={events.refetch}
              icon={<RefreshCw className="h-3 w-3" />}
            >
              Refresh
            </Button>
          </>
        }
      >
        <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-4">
          <Field label="Attack type">
            {(id) => (
              <Select
                id={id}
                value={attackType}
                onChange={(event) => {
                  setAttackType(event.target.value as AttackType | '')
                  setPage(0)
                }}
              >
                <option value="">All types</option>
                {ATTACK_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {attackLabel(type)}
                  </option>
                ))}
              </Select>
            )}
          </Field>

          <Field label="Severity">
            {(id) => (
              <Select
                id={id}
                value={severity}
                onChange={(event) => {
                  setSeverity(event.target.value as Severity | '')
                  setPage(0)
                }}
              >
                <option value="">All severities</option>
                {SEVERITY_ORDER.map((level) => (
                  <option key={level} value={level}>
                    {level}
                  </option>
                ))}
              </Select>
            )}
          </Field>

          <Field label="Triage status">
            {(id) => (
              <Select
                id={id}
                value={status}
                onChange={(event) => {
                  setStatus(event.target.value as EventStatus | '')
                  setPage(0)
                }}
              >
                <option value="">Any status</option>
                {STATUSES.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </Select>
            )}
          </Field>

          <div className="flex items-end">
            <Button variant="ghost" onClick={resetFilters} disabled={!hasFilters} className="w-full">
              Clear filters
            </Button>
          </div>
        </div>

        {actionError && (
          <p role="alert" className="mt-3 rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-200">
            {actionError}
          </p>
        )}

        <div className="mt-4">
          {events.loading ? (
            <LoadingState label="Loading security events…" />
          ) : events.error && items.length === 0 ? (
            <ErrorState error={events.error} onRetry={events.refetch} />
          ) : items.length === 0 ? (
            <EmptyState
              icon={<ShieldCheck className="h-5 w-5" />}
              title={hasFilters ? 'No events match these filters' : 'No security events recorded'}
              description={
                hasFilters
                  ? 'Try widening the filter, or clear it to see every event.'
                  : 'Run an attack from the Simulator page and the detections will appear here.'
              }
              action={
                hasFilters ? (
                  <Button onClick={resetFilters}>Clear filters</Button>
                ) : undefined
              }
            />
          ) : (
            <ul className="space-y-2.5">
              {items.map((event) => (
                <li key={event.id ?? event.timestamp} className="space-y-1.5">
                  <AttackAlert event={event} />
                  {event.id != null && (
                    <div className="flex flex-wrap items-center gap-2 pl-3">
                      <Pill>#{event.id}</Pill>
                      <Button
                        size="sm"
                        variant="ghost"
                        loading={busyId === event.id}
                        disabled={event.status === 'ACKNOWLEDGED'}
                        onClick={() => triage(event.id as number, 'ACKNOWLEDGED')}
                      >
                        Acknowledge
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        loading={busyId === event.id}
                        disabled={event.status === 'RESOLVED'}
                        icon={<CheckCircle2 className="h-3 w-3" />}
                        onClick={() => triage(event.id as number, 'RESOLVED')}
                      >
                        Resolve
                      </Button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>

        {total > PAGE_SIZE && (
          <nav
            aria-label="Security event pages"
            className="mt-4 flex items-center justify-between border-t border-base-700/70 pt-3 text-2xs text-ink-muted"
          >
            <span>
              Showing {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, total)} of {total}
            </span>
            <div className="flex gap-2">
              <Button size="sm" disabled={page === 0} onClick={() => setPage((value) => value - 1)}>
                Previous
              </Button>
              <Button
                size="sm"
                disabled={!events.data?.has_more}
                onClick={() => setPage((value) => value + 1)}
              >
                Next
              </Button>
            </div>
          </nav>
        )}
      </Panel>
    </div>
  )
}
