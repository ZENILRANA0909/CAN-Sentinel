import clsx from 'clsx'
import { Loader2 } from 'lucide-react'
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from 'react'
import { useId } from 'react'

type Variant = 'primary' | 'secondary' | 'danger' | 'ghost'

const VARIANTS: Record<Variant, string> = {
  primary:
    'bg-accent/15 text-sky-200 border-accent/50 hover:bg-accent/25 hover:border-accent disabled:hover:bg-accent/15',
  secondary:
    'bg-base-800 text-ink border-base-600 hover:border-base-500 hover:bg-base-700 disabled:hover:bg-base-800',
  danger:
    'bg-red-500/15 text-red-200 border-red-500/50 hover:bg-red-500/25 hover:border-red-400 disabled:hover:bg-red-500/15',
  ghost:
    'bg-transparent text-ink-muted border-transparent hover:bg-base-800 hover:text-ink disabled:hover:bg-transparent',
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: 'sm' | 'md'
  loading?: boolean
  icon?: ReactNode
}

export function Button({
  variant = 'secondary',
  size = 'md',
  loading = false,
  icon,
  children,
  className,
  disabled,
  ...rest
}: ButtonProps) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={clsx(
        'inline-flex items-center justify-center gap-1.5 rounded-md border font-medium transition',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1 focus-visible:ring-offset-base-950',
        'disabled:cursor-not-allowed disabled:opacity-50',
        size === 'sm' ? 'px-2.5 py-1 text-2xs' : 'px-3 py-1.5 text-xs',
        VARIANTS[variant],
        className,
      )}
    >
      {loading ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
      ) : (
        icon && (
          <span className="shrink-0" aria-hidden="true">
            {icon}
          </span>
        )
      )}
      {children}
    </button>
  )
}

const FIELD_CLASSES =
  'w-full rounded-md border border-base-600 bg-base-900/70 px-2.5 py-1.5 text-xs text-ink placeholder:text-ink-faint ' +
  'transition focus:border-accent/70 focus:outline-none focus-visible:ring-1 focus-visible:ring-accent ' +
  'disabled:cursor-not-allowed disabled:opacity-50'

interface FieldProps {
  label: string
  hint?: ReactNode
  error?: string | null
  children: (id: string, describedBy: string | undefined) => ReactNode
  className?: string
}

/** Wraps a control with its label, hint and error, wired up for screen readers. */
export function Field({ label, hint, error, children, className }: FieldProps) {
  const id = useId()
  const hintId = hint || error ? `${id}-hint` : undefined
  return (
    <div className={clsx('space-y-1', className)}>
      <label htmlFor={id} className="block text-2xs font-medium uppercase tracking-wide text-ink-faint">
        {label}
      </label>
      {children(id, hintId)}
      {(hint || error) && (
        <p id={hintId} className={clsx('text-2xs', error ? 'text-red-300' : 'text-ink-faint')}>
          {error ?? hint}
        </p>
      )}
    </div>
  )
}

export function TextInput({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...rest} className={clsx(FIELD_CLASSES, className)} />
}

export function Select({ className, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select {...rest} className={clsx(FIELD_CLASSES, 'pr-8', className)}>
      {children}
    </select>
  )
}

interface ToggleProps {
  checked: boolean
  onChange: (next: boolean) => void
  label: string
  description?: string
  disabled?: boolean
}

export function Toggle({ checked, onChange, label, description, disabled = false }: ToggleProps) {
  return (
    <label
      className={clsx(
        'flex items-start justify-between gap-4 rounded-md border border-base-700 bg-base-900/50 px-3 py-2.5',
        disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer hover:border-base-600',
      )}
    >
      <span className="min-w-0">
        <span className="block text-xs font-medium text-ink">{label}</span>
        {description && <span className="mt-0.5 block text-2xs text-ink-muted">{description}</span>}
      </span>
      <input
        type="checkbox"
        role="switch"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
        className="peer sr-only"
      />
      <span
        aria-hidden="true"
        className={clsx(
          'relative mt-0.5 h-5 w-9 shrink-0 rounded-full border transition',
          'peer-focus-visible:ring-2 peer-focus-visible:ring-accent peer-focus-visible:ring-offset-1 peer-focus-visible:ring-offset-base-950',
          checked ? 'border-accent/60 bg-accent/30' : 'border-base-600 bg-base-800',
        )}
      >
        <span
          className={clsx(
            'absolute top-0.5 h-3.5 w-3.5 rounded-full transition-all',
            checked ? 'left-[1.15rem] bg-sky-300' : 'left-0.5 bg-ink-faint',
          )}
        />
      </span>
    </label>
  )
}

interface SegmentedProps<T extends string> {
  options: Array<{ value: T; label: string; tone?: 'default' | 'danger' }>
  value: T
  onChange: (value: T) => void
  ariaLabel: string
  disabled?: boolean
}

/** Radio group styled as a segmented control — used for simulator mode. */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
  disabled = false,
}: SegmentedProps<T>) {
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      className="flex flex-wrap gap-1.5 rounded-lg border border-base-700 bg-base-900/60 p-1.5"
    >
      {options.map((option) => {
        const active = option.value === value
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            disabled={disabled}
            onClick={() => onChange(option.value)}
            className={clsx(
              'flex-1 rounded-md px-3 py-2 text-xs font-medium transition',
              'focus:outline-none focus-visible:ring-2 focus-visible:ring-accent',
              'disabled:cursor-not-allowed disabled:opacity-50',
              active && option.tone === 'danger' && 'bg-red-500/20 text-red-200 ring-1 ring-red-500/50',
              active && option.tone !== 'danger' && 'bg-accent/20 text-sky-200 ring-1 ring-accent/50',
              !active && 'text-ink-muted hover:bg-base-800 hover:text-ink',
            )}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}
