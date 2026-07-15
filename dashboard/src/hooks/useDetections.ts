'use client'

import { useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getDetections, getDetection, getDetectionTrace } from '@/lib/api/detections'
import { API_BASE, resolveKey } from '@/lib/api/client'

export function useDetections() {
  const queryClient = useQueryClient()

  // Live updates: subscribe to the server's SSE stream and refetch on each event, so
  // detections appear as executions arrive (push channel or background poll) without a
  // manual refresh.
  useEffect(() => {
    const key = resolveKey()
    const url = `${API_BASE}/api/v1/stream${key ? `?token=${encodeURIComponent(key)}` : ''}`
    let es: EventSource | null = null
    try {
      es = new EventSource(url)
      es.onmessage = () => {
        queryClient.invalidateQueries({ queryKey: ['detections'] })
      }
    } catch {
      // EventSource unavailable — fall back to the query's normal cadence.
    }
    return () => es?.close()
  }, [queryClient])

  return useQuery({
    queryKey: ['detections'],
    queryFn: getDetections,
  })
}

// Detail view: fetch one detection by id via GET /api/v1/detections/{id}, so a cold
// deep link resolves without depending on the full list being loaded.
export function useDetection(id: string) {
  return useQuery({
    queryKey: ['detection', id],
    queryFn: () => getDetection(id),
    enabled: Boolean(id),
  })
}

// The per-node execution trace for the detail view's in-app trace panel.
export function useDetectionTrace(id: string) {
  return useQuery({
    queryKey: ['detection-trace', id],
    queryFn: () => getDetectionTrace(id),
    enabled: Boolean(id),
  })
}
