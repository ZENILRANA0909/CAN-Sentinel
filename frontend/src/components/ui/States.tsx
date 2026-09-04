import clsx from 'clsx'
import { AlertTriangle, Inbox, Loader2, RefreshCw, WifiOff } from 'lucide-react'
import type { ReactNode } from 'react'
import { ApiRequestError } from '@/services/api'

/**
 * The three states every data view must handle.
 *
 * A blank panel is never acceptable: the operator has to be able to tell the
 * difference between "still loading", "nothing to show" and "this is broken".
 */

export function LoadingState({ label = 'Loading…', className }: { label?: string; className?: string }) {
  return (
    <div
      role="status"
      aria-live="polite"
      className={clsx('flex items-center justify-center gap-2 py-10 text-sm text-ink-muted', className)}
    >
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
      {label}
    </div>
  )
}

export function EmptyState({
  title,
  description,
  icon,
  action,
  className,
}: {
  title: string
  description?: ReactNode
  icon?: ReactNode
  action?: ReactNode
  className?: string
}) {
  return (
    <div className={clsx('flex flex-col items-center justify-center px-6 py-10 text-center', className)}>
      <span className="mb-3 rounded-full bg-base-800 p-2.5 text-ink-faint" aria-hidden="true">
        {icon ?? <Inbox className="h-5 w-5" />}
      </span>
      <p className="text-sm font-medium text-ink">{title}</p>
      {description && <p className="mt-1 max-w-sm text-xs text-ink-muted">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

export function ErrorState({
  error,
  onRetry,
  className,
}: {
  error: ApiRequestError | Error | string
  onRetry?: () => void
  className?: string
}) {
  const offline = error instanceof ApiRequestError && error.isOffline
  const message = typeof error === 'string' ? error : error.message

  return (
    <div
      role="alert"
      className={clsx('flex flex-col items-center justify-center px-6 py-10 text-center', className)}
    >
      <span className="mb-3 rounded-full bg-red-500/10 p-2.5 text-red-300" aria-hidden="true">
        {offline ? <WifiOff className="h-5 w-5" /> : <AlertTriangle className="h-5 w-5" />}
      </span>
      <p className="text-sm font-medium text-ink">
        {offline ? 'Backend unreachable' : 'Could not load this view'}
      </p>
      <p className="mt-1 max-w-md text-xs text-ink-muted">{message}</p>
      {offline && (
        <p className="mt-2 max-w-md text-2xs text-ink-faint">
          Check that the API is running on the configured address, then retry.
        </p>
      )}
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-4 inline-flex items-center gap-1.5 rounded-md border border-base-600 bg-base-800 px-3 py-1.5 text-xs font-medium text-ink transition hover:border-accent/60 hover:text-sky-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
          Retry
        </button>
      )}
    </div>
  )
}

/** Shimmer placeholder used while a panel's first payload is in flight. */
export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx('animate-pulse rounded bg-base-800/80', className)} aria-hidden="true" />
}
