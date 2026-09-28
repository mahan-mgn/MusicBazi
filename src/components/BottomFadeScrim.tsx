import { memo } from 'react'

/**
 * The floor the floating liquid glass bars sit on: the page's own background color,
 * faded in from transparent at the top to solid at the very bottom using a 16-stop
 * cubic ease-in curve matching BitChord's BottomFadeScrim.
 *
 * Height dynamically animates between 180px (default/inline) and 254px (with expanded player).
 */
function BottomFadeScrim() {
  // 16 color stops using EaseInCubic (t^3)
  const stops = Array.from({ length: 16 }, (_, i) => {
    const t = i / 15
    const alphaPct = (Math.pow(t, 3) * 100).toFixed(2)
    const posPct = (t * 100).toFixed(1)
    return `color-mix(in srgb, var(--bg) ${alphaPct}%, transparent) ${posPct}%`
  }).join(', ')

  return (
    <div
      aria-hidden="true"
      className="bottom-fade-scrim pointer-events-none fixed inset-x-0 bottom-0 z-20 sm:hidden"
      style={{
        background: `linear-gradient(to bottom, ${stops})`,
      }}
    />
  )
}

export default memo(BottomFadeScrim)
