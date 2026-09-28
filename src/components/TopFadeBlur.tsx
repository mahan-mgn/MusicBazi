import { memo } from 'react'

/**
 * Progressive top blur and readability scrim matching BitChord's TopFadeBlur.
 * Ramps blur down across a 32px run beneath the sticky header to remove hard
 * divider lines while keeping glyphs readable.
 */
function TopFadeBlur() {
  // 12 stops easing out via EaseOutCubic: 1 - (1 - t)^3
  const scrimStops = Array.from({ length: 12 }, (_, i) => {
    const t = i / 11
    const factor = 1 - Math.pow(1 - t, 3)
    const alphaPct = (0.42 * (1 - factor) * 100).toFixed(2)
    const pos = (t * 100).toFixed(1)
    return `color-mix(in srgb, var(--panel) ${alphaPct}%, transparent) ${pos}%`
  }).join(', ')

  return (
    <div
      aria-hidden="true"
      className="top-fade-blur pointer-events-none fixed inset-x-0 top-0 z-25 sm:hidden"
      style={{
        height: 'calc(var(--header-h) + 32px)',
        WebkitMaskImage:
          'linear-gradient(to bottom, black 0%, black var(--header-h), rgba(0,0,0,0.75) calc(var(--header-h) + 12px), rgba(0,0,0,0.2) calc(var(--header-h) + 24px), transparent 100%)',
        maskImage:
          'linear-gradient(to bottom, black 0%, black var(--header-h), rgba(0,0,0,0.75) calc(var(--header-h) + 12px), rgba(0,0,0,0.2) calc(var(--header-h) + 24px), transparent 100%)',
        WebkitBackdropFilter: 'blur(8px) saturate(150%)',
        backdropFilter: 'blur(8px) saturate(150%)',
      }}
    >
      <div
        className="size-full"
        style={{
          background: `linear-gradient(to bottom, ${scrimStops})`,
        }}
      />
    </div>
  )
}

export default memo(TopFadeBlur)
