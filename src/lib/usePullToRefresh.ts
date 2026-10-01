import { useEffect, useRef, useState } from 'react'
import { haptic } from './native'

/** حداقل کشش برای شروع تازه‌سازی (پیکسل) */
export const PULL_THRESHOLD = 64
/** سقف جابجایی دیداری اندیکاتور */
export const MAX_PULL = 90

/**
 * هوک ژست Pull-to-Refresh روی دستگاه‌های لمسی و موبایل.
 * در بالای صفحه (scrollY === 0) با کشیدن به پایین فیدبک لمسی داده
 * و پس از رها شدن تابع onRefresh را اجرا می‌کند.
 */
export function usePullToRefresh(onRefresh: () => Promise<void> | void, enabled = true) {
  const [pullDistance, setPullDistance] = useState(0)
  const [refreshing, setRefreshing] = useState(false)
  const refreshRef = useRef(onRefresh)
  refreshRef.current = onRefresh

  useEffect(() => {
    if (!enabled || typeof window === 'undefined') return

    let startY = 0
    let tracking = false
    let passedThreshold = false

    const onTouchStart = (e: TouchEvent) => {
      if (window.scrollY > 4 || refreshing) return
      startY = e.touches[0].clientY
      tracking = true
      passedThreshold = false
    }

    const onTouchMove = (e: TouchEvent) => {
      if (!tracking || refreshing) return
      const currentY = e.touches[0].clientY
      const dy = currentY - startY
      if (dy <= 0) {
        setPullDistance(0)
        return
      }

      if (window.scrollY > 0) {
        tracking = false
        setPullDistance(0)
        return
      }

      // مقاومت کشسانی لاستیکی
      const distance = Math.min(MAX_PULL, dy * 0.45)
      setPullDistance(distance)

      if (distance >= PULL_THRESHOLD && !passedThreshold) {
        passedThreshold = true
        haptic.select()
      } else if (distance < PULL_THRESHOLD && passedThreshold) {
        passedThreshold = false
      }
    }

    const onTouchEnd = async () => {
      if (!tracking) return
      tracking = false

      if (passedThreshold && !refreshing) {
        setRefreshing(true)
        setPullDistance(PULL_THRESHOLD * 0.75)
        try {
          await Promise.resolve(refreshRef.current())
        } finally {
          setRefreshing(false)
          setPullDistance(0)
        }
      } else {
        setPullDistance(0)
      }
    }

    window.addEventListener('touchstart', onTouchStart, { passive: true })
    window.addEventListener('touchmove', onTouchMove, { passive: true })
    window.addEventListener('touchend', onTouchEnd, { passive: true })
    window.addEventListener('touchcancel', onTouchEnd, { passive: true })

    return () => {
      window.removeEventListener('touchstart', onTouchStart)
      window.removeEventListener('touchmove', onTouchMove)
      window.removeEventListener('touchend', onTouchEnd)
      window.removeEventListener('touchcancel', onTouchEnd)
    }
  }, [enabled, refreshing])

  return { pullDistance, refreshing }
}
