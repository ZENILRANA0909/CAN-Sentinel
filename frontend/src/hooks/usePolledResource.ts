import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiRequestError } from '@/services/api'

export interface PolledResource<T> {
  data: T | null
  error: ApiRequestError | null
  /** True only for the very first load, so a refresh never blanks the screen. */
  loading: boolean
  /** True while a background refresh is in flight. */
  refreshing: boolean
  lastUpdated: number | null
  refetch: () => Promise<void>
}

interface Options {
  /** Poll interval in milliseconds; 0 disables polling. */
  intervalMs?: number
  enabled?: boolean
  /** Pause polling while the browser tab is hidden. */
  pauseWhenHidden?: boolean
}

/**
 * Fetch a resource once and optionally keep it fresh on an interval.
 *
 * Most live numbers arrive over the WebSocket; this hook covers the data that
 * genuinely needs a query (paged history, aggregates). It keeps the previous
 * value visible during a refresh and while an error is being retried, so a
 * brief backend hiccup never empties a populated dashboard.
 */
export function usePolledResource<T>(
  fetcher: () => Promise<T>,
  deps: readonly unknown[],
  { intervalMs = 0, enabled = true, pauseWhenHidden = true }: Options = {},
): PolledResource<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<ApiRequestError | null>(null)
  const [loading, setLoading] = useState(enabled)
  const [refreshing, setRefreshing] = useState(false)
  const [lastUpdated, setLastUpdated] = useState<number | null>(null)

  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher
  const mounted = useRef(true)
  const inFlight = useRef(false)
  const hasLoaded = useRef(false)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  const load = useCallback(async () => {
    // Overlapping requests would fight over the same state; skip instead.
    if (inFlight.current) return
    inFlight.current = true
    if (hasLoaded.current) setRefreshing(true)
    try {
      const result = await fetcherRef.current()
      if (!mounted.current) return
      setData(result)
      setError(null)
      setLastUpdated(Date.now())
      hasLoaded.current = true
    } catch (caught) {
      if (!mounted.current) return
      setError(
        caught instanceof ApiRequestError
          ? caught
          : new ApiRequestError('Unexpected error while loading data.', 0, 'unknown'),
      )
    } finally {
      if (mounted.current) {
        setLoading(false)
        setRefreshing(false)
      }
      inFlight.current = false
    }
  }, [])

  useEffect(() => {
    if (!enabled) {
      setLoading(false)
      return
    }
    void load()
    if (intervalMs <= 0) return

    const timer = window.setInterval(() => {
      if (pauseWhenHidden && document.visibilityState === 'hidden') return
      void load()
    }, intervalMs)

    // Refresh straight away when the operator comes back to the tab.
    const onVisible = () => {
      if (document.visibilityState === 'visible') void load()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisible)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, intervalMs, pauseWhenHidden, load, ...deps])

  return { data, error, loading, refreshing, lastUpdated, refetch: load }
}
