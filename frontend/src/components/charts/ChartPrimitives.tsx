import type { ReactNode } from 'react'

interface TooltipRow {
  label: string
  value: ReactNode
  color?: string
}

/** Consistent tooltip shell so every chart reads the same way. */
export function TooltipCard({ title, rows }: { title: ReactNode; rows: TooltipRow[] }) {

  return (
    <div className="rounded-lg border border-base-600 bg-base-900/95 px-3 py-2 shadow-panel backdrop-blur">
      <p className="mb-1 text-2xs font-medium uppercase tracking-wide text-ink-faint">{title}</p>
      <ul className="space-y-0.5">
        {rows.map((row) => (
          <li key={row.label} className="flex items-center gap-2 text-xs">
            {row.color && (
              <span
                className="h-2 w-2 shrink-0 rounded-sm"
                style={{ backgroundColor: row.color }}
                aria-hidden="true"
              />
            )}
            <span className="text-ink-muted">{row.label}</span>
            <span className="ml-auto font-mono tabular-nums text-ink">{row.value}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/**
 * A textual equivalent of a chart for assistive technology.
 *
 * Recharts renders an SVG with no meaningful semantics; this table carries the
 * same numbers for screen readers without affecting the visual layout.
 */
export function ChartDescription({
  caption,
  headers,
  rows,
}: {
  caption: string
  headers: string[]
  rows: Array<Array<string | number>>
}) {
  return (
    <table className="sr-only">
      <caption>{caption}</caption>
      <thead>
        <tr>
          {headers.map((header) => (
            <th key={header} scope="col">
              {header}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, index) => (
          <tr key={index}>
            {row.map((cell, cellIndex) => (
              <td key={cellIndex}>{cell}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}
