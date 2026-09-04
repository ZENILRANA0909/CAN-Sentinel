import { Radio } from 'lucide-react'
import { CanMessageRow } from '@/components/traffic/CanMessageRow'
import { EmptyState } from '@/components/ui/States'
import type { CanMessage } from '@/types/api'

interface TrafficTableProps {
  messages: CanMessage[]
  /** Frames newer than this timestamp get the "just arrived" highlight. */
  highlightAfter?: number
  emptyTitle?: string
  emptyDescription?: string
  maxHeight?: string
}

const COLUMNS = [
  { key: 'time', label: 'Time' },
  { key: 'id', label: 'CAN ID' },
  { key: 'signal', label: 'Signal' },
  { key: 'dlc', label: 'DLC' },
  { key: 'data', label: 'Data' },
  { key: 'decoded', label: 'Decoded' },
  { key: 'source', label: 'Source' },
  { key: 'status', label: 'Status' },
] as const

export function TrafficTable({
  messages,
  highlightAfter = 0,
  emptyTitle = 'No frames match the current filter',
  emptyDescription = 'Adjust the filters, or start the simulator to generate traffic.',
  maxHeight = '32rem',
}: TrafficTableProps) {
  if (messages.length === 0) {
    return (
      <EmptyState
        icon={<Radio className="h-5 w-5" />}
        title={emptyTitle}
        description={emptyDescription}
      />
    )
  }

  return (
    <div className="overflow-auto" style={{ maxHeight }}>
      <table className="data-table">
        <caption className="sr-only">
          Live CAN bus traffic, newest first. {messages.length} frames shown.
        </caption>
        <thead>
          <tr>
            {COLUMNS.map((column) => (
              <th key={column.key} scope="col">
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {messages.map((message, index) => (
            <CanMessageRow
              key={`${message.timestamp}-${message.can_id}-${index}`}
              message={message}
              isNew={message.timestamp > highlightAfter}
            />
          ))}
        </tbody>
      </table>
    </div>
  )
}
