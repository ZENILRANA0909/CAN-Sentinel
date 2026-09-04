import clsx from 'clsx'
import {
  Activity,
  BarChart3,
  Cpu,
  LayoutDashboard,
  Radio,
  Settings,
  ShieldAlert,
  X,
} from 'lucide-react'
import { NavLink } from 'react-router-dom'
import { useLiveStatus } from '@/hooks/liveData'

const NAV_ITEMS = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/traffic', label: 'Live Traffic', icon: Radio, end: false },
  { to: '/security', label: 'Security', icon: ShieldAlert, end: false },
  { to: '/analytics', label: 'Analytics', icon: BarChart3, end: false },
  { to: '/simulator', label: 'Simulator', icon: Activity, end: false },
  { to: '/system', label: 'System', icon: Cpu, end: false },
  { to: '/settings', label: 'Settings', icon: Settings, end: false },
] as const

interface SidebarProps {
  open: boolean
  onClose: () => void
}

export function Sidebar({ open, onClose }: SidebarProps) {
  const { activeAlerts, systemStatus } = useLiveStatus()

  return (
    <>
      {/* Scrim for the mobile drawer. */}
      <div
        className={clsx(
          'fixed inset-0 z-30 bg-black/60 transition-opacity lg:hidden',
          open ? 'opacity-100' : 'pointer-events-none opacity-0',
        )}
        onClick={onClose}
        aria-hidden="true"
      />
      <aside
        className={clsx(
          'fixed inset-y-0 left-0 z-40 flex w-60 shrink-0 flex-col border-r border-base-800 bg-base-900/95 backdrop-blur transition-transform',
          'lg:static lg:translate-x-0',
          open ? 'translate-x-0' : '-translate-x-full',
        )}
        aria-label="Primary"
      >
        <div className="flex items-center justify-between gap-2 border-b border-base-800 px-4 py-4">
          <div className="flex items-center gap-2.5">
            <span
              className="grid h-9 w-9 place-items-center rounded-lg bg-accent/15 ring-1 ring-inset ring-accent/40"
              aria-hidden="true"
            >
              <ShieldAlert className="h-5 w-5 text-sky-300" />
            </span>
            <div className="leading-tight">
              <p className="text-sm font-semibold tracking-tight text-ink">CAN-Sentinel</p>
              <p className="text-2xs text-ink-faint">CAN Network Security</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-ink-faint hover:bg-base-800 hover:text-ink lg:hidden"
            aria-label="Close navigation"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <nav className="flex-1 space-y-0.5 overflow-y-auto p-2">
          {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              onClick={onClose}
              className={({ isActive }) =>
                clsx(
                  'group flex items-center gap-2.5 rounded-md px-3 py-2 text-xs font-medium transition',
                  isActive
                    ? 'bg-accent/12 text-sky-200 ring-1 ring-inset ring-accent/30'
                    : 'text-ink-muted hover:bg-base-800 hover:text-ink',
                )
              }
            >
              {({ isActive }) => (
                <>
                  <Icon
                    className={clsx('h-4 w-4 shrink-0', isActive ? 'text-sky-300' : 'text-ink-faint')}
                    aria-hidden="true"
                  />
                  <span className="flex-1">{label}</span>
                  {to === '/security' && activeAlerts > 0 && (
                    <span
                      className="rounded-full bg-red-500/20 px-1.5 py-0.5 text-2xs font-semibold text-red-300 ring-1 ring-inset ring-red-500/40"
                      aria-label={`${activeAlerts} active alerts`}
                    >
                      {activeAlerts > 99 ? '99+' : activeAlerts}
                    </span>
                  )}
                </>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-base-800 px-4 py-3 text-2xs text-ink-faint">
          <p className="flex items-center justify-between">
            <span>Version</span>
            <span className="mono text-ink-muted">{systemStatus?.version ?? '1.0.0'}</span>
          </p>
          <p className="mt-1 flex items-center justify-between">
            <span>Environment</span>
            <span className="mono text-ink-muted">{systemStatus?.environment ?? '—'}</span>
          </p>
          <p className="mt-2 leading-relaxed text-ink-faint/80">
            Demonstration system. Not for deployment in a real vehicle.
          </p>
        </div>
      </aside>
    </>
  )
}
