// Extracted verbatim from the Pisama monorepo (landing/broadsheet/primitives.tsx):
// the ring + amber "evidence" dot wordmark.
export function PisamaMark({ size = 26, color = 'currentColor' }: { size?: number; color?: string }) {
  return (
    <svg viewBox="0 0 64 64" width={size} height={size} aria-hidden="true">
      <circle cx="32" cy="32" r="22" stroke={color} strokeWidth="2" opacity=".9" fill="none" />
      <circle cx="40" cy="26" r="4.5" fill="#E8B341" />
    </svg>
  )
}
