import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Scroll tracking for the floating navigation bar matching BitChord's
 * FloatingTabBarScrollConnection.
 *
 * Scrolling down by at least 50px folds the navigation and player controls
 * into a single inline row (only when an active track is present).
 * Scrolling back up by 30px (or reaching page top) expands it back into the
 * two stacked pills.
 */
export function useFloatingTabBarScroll(enabled = true, scrollThreshold = 50) {
  const [isInline, setIsInline] = useState(false)
  const lastYRef = useRef(0)
  const accumulatedRef = useRef(0)
  const rafRef = useRef(0)

  const expand = useCallback(() => {
    accumulatedRef.current = 0
    setIsInline(false)
  }, [])

  const inline = useCallback(() => {
    if (!enabled) return
    accumulatedRef.current = 0
    setIsInline(true)
  }, [enabled])

  useEffect(() => {
    if (!enabled) {
      setIsInline(false)
      accumulatedRef.current = 0
      return
    }

    if (typeof window === 'undefined') return

    lastYRef.current = window.scrollY

    const onScroll = () => {
      if (rafRef.current) return

      rafRef.current = requestAnimationFrame(() => {
        rafRef.current = 0
        const currentY = window.scrollY
        const delta = currentY - lastYRef.current
        lastYRef.current = currentY

        // Reaching near the top of the page always expands the bar
        if (currentY < 40) {
          accumulatedRef.current = 0
          setIsInline(false)
          return
        }

        // Ignore subpixel micro-jitter
        if (Math.abs(delta) < 2) return

        // Reset accumulation if scroll direction changes
        if ((delta > 0 && accumulatedRef.current < 0) || (delta < 0 && accumulatedRef.current > 0)) {
          accumulatedRef.current = 0
        }

        accumulatedRef.current += delta

        if (accumulatedRef.current >= scrollThreshold) {
          // Scrolled down enough -> fold inline
          setIsInline(true)
          accumulatedRef.current = 0
        } else if (accumulatedRef.current <= -30) {
          // Scrolled up enough -> expand responsively
          setIsInline(false)
          accumulatedRef.current = 0
        }
      })
    }

    window.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      window.removeEventListener('scroll', onScroll)
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
    }
  }, [enabled, scrollThreshold])

  return { isInline: enabled && isInline, expand, inline }
}
