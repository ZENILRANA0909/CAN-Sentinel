import clsx from 'clsx'
import type { ReactNode } from 'react'

interface PanelProps {
  title?: ReactNode
  subtitle?: ReactNode
  /** Rendered at the far right of the header row. */
  actions?: ReactNode
  icon?: ReactNode
  children: ReactNode
  className?: string
  bodyClassName?: string
  /** Remove body padding, for panels whose child is a full-bleed table. */
  flush?: boolean
}

/**
 * The single surface every page is built from.
 *
 * One consistent container keeps the dashboard reading as a product rather
 * than a collection of independently styled widgets.
 */
export function Panel({
  title,
  subtitle,
  actions,
  icon,
  children,
  className,
  bodyClassName,
  flush = false,
}: PanelProps) {
  return (
    <section
      className={clsx(
        'rounded-xl border border-base-700/80 bg-base-850/70 bg-panel-sheen shadow-panel backdrop-blur-[2px]',
        className,
      )}
    >
      {(title || actions) && (
        <header className="flex items-start justify-between gap-4 border-b border-base-700/70 px-4 py-3">
          <div className="flex min-w-0 items-start gap-2.5">
            {icon && <span className="mt-0.5 text-ink-faint">{icon}</span>}
            <div className="min-w-0">
              {title && (
                <h2 className="truncate text-sm font-semibold tracking-tight text-ink">{title}</h2>
              )}
              {subtitle && <p className="mt-0.5 text-xs text-ink-muted">{subtitle}</p>}
            </div>
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={clsx(!flush && 'p-4', bodyClassName)}>{children}</div>
    </section>
  )
}
