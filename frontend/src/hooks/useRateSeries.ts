import { useMemo } from 'react'
import { useLiveStatus } from '@/hooks/liveData'
import { usePolledResource } from '@/hooks/usePolledResource'
import { api } from '@/services/api'
import type { RatePoint } from '@/types/api'

/**
 * The rate chart's data, seeded from history and extended live.
 *
 * The WebSocket only carries points from the moment the page connected, so a
 * freshly opened dashboard would show an empty chart for the first minute.
 * Seeding once from `/api/traffic/rate` and then appending the streamed points
 * gives an immediately populated chart that stays live.
 */
export function useRateSeries(points = 120) {
  const { rateHistory } = useLiveStatus()
  const seed = usePolledResource(() => api.trafficRate(points), [points], {
    // Refreshed rarely: the live stream is the primary source after the seed.
    intervalMs: 60_000,
  })

  const series = useMemo<RatePoint[]>(() => {
    const seeded = seed.data?.history ?? []
    if (rateHistory.length === 0) return seeded
    if (seeded.length === 0) return rateHistory

    const boundary = seeded[seeded.length - 1]?.timestamp ?? 0
    const live = rateHistory.filter((point) => point.timestamp > boundary)
    const merged = [...seeded, ...live]
    return merged.length > points ? merged.slice(merged.length - points) : merged
  }, [seed.data, rateHistory, points])

  return {
    series,
    floodThreshold: seed.data?.flood_threshold_msg_per_s,
    suspiciousThreshold: seed.data?.flood_suspicious_threshold_msg_per_s,
    peakRate: seed.data?.peak_rate_msg_per_s ?? 0,
    loading: seed.loading,
    error: seed.error,
    refetch: seed.refetch,
  }
}
