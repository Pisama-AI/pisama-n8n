'use client'

import { useQuery } from '@tanstack/react-query'
import { getDetections } from '@/lib/api/detections'

export function useDetections() {
  return useQuery({
    queryKey: ['detections'],
    queryFn: getDetections,
  })
}
