import { DetectionDetailClient } from './DetectionDetailClient'

export default async function DetectionDetailPage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = await params
  return <DetectionDetailClient id={id} />
}
