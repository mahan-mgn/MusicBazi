import { useEffect, useRef } from 'react'
import { haptic } from './native'
import { dirSign, reducedMotion } from './motion'

/** آستانه فاصله بر حسب پیکسل برای ثبت سوایپ */
export const THRESHOLD = 56
/** آستانه سرعت پرتاب (flick) بر حسب پیکسل بر میلی‌ثانیه */
export const VELOCITY = 0.45
/** سقف بیشترین جابجایی دیداری زیر انگشت */
export const MAX_SHIFT = 96
/** حداقل جابجایی برای تشخیص جهت افقی */
export const SLOP = 8

/**
 * بررسی اینکه آیا فاصله یا سرعت سوایپ به حد نصاب برای ثبت عملیات رسیده است یا خیر.
 */
export function shouldCommitRowSwipe(dx: number, velocity: number): boolean {
  if (Math.abs(dx) >= THRESHOLD) return true
  if (Math.abs(velocity) > VELOCITY && Math.sign(velocity) === Math.sign(dx)) return true
  return false
}

interface Options<T extends HTMLElement = HTMLDivElement> {
  /** رفرنس خارجی اختیاری اگر المنتی از قبل رفرنس دارد (مثلاً ترکیب با useLongPress) */
  ref?: React.RefObject<T | null>
  /** سوایپ از سمت شروع به پایان (در راست‌به‌چپ: راست به چپ، در چپ‌به‌راست: چپ به راست) */
  onStartToEnd?: () => void
  /** سوایپ از سمت پایان به شروع */
  onEndToStart?: () => void
  enabled?: boolean
}

/**
 * هوک ژست سوایپ افقی سطرهای آهنگ با بازگشت فنری (Spring-Back).
 *
 * الهام‌گرفته از رفتار `SongRow` در BitChord:
 *  - با سوایپ افقی، ردیف جابجا شده و آیکون اکشن (مانند صف) را آشکار می‌کند.
 *  - با عبور از آستانه (۵۶ پیکسل یا پرتاب سریع)، فیدبک لمسی می‌دهد.
 *  - بعد از اتمام، با فیزیک بازگشت فنری سر جای خود برمی‌گردد و عملیات را اجرا می‌کند.
 *  - در صورت تشخیص اسکرول عمودی، بلافاصله ژست لغو می‌شود تا اسکرول صفحه بدون تداخل بماند.
 */
export function useRowSwipe<T extends HTMLElement = HTMLDivElement>({
  ref: externalRef,
  onStartToEnd,
  onEndToStart,
  enabled = true,
}: Options<T>) {
  const internalRef = useRef<T>(null)
  const targetRef = externalRef || internalRef
  const handlers = useRef({ onStartToEnd, onEndToStart })
  handlers.current = { onStartToEnd, onEndToStart }

  useEffect(() => {
    const el = targetRef.current
    if (!el || !enabled) return

    let startX = 0
    let startY = 0
    let lastX = 0
    let lastAt = 0
    let prevX = 0
    let prevAt = 0
    let horizontal: boolean | null = null
    let active = false
    let armed = false
    let didDrag = false

    const paint = (dx: number) => {
      const absDx = Math.abs(dx)
      const sign = Math.sign(dx)
      const shift = absDx <= MAX_SHIFT ? dx : sign * (MAX_SHIFT + (absDx - MAX_SHIFT) * 0.28)
      el.style.transform = `translateX(${shift}px)`

      if (absDx >= THRESHOLD) {
        if (!armed) {
          armed = true
          haptic.select()
        }
      } else if (armed && absDx < THRESHOLD * 0.75) {
        armed = false
      }
    }

    const settle = () => {
      el.style.transition = reducedMotion()
        ? 'none'
        : 'transform 0.32s cubic-bezier(0.22, 1, 0.36, 1)'
      el.style.transform = ''
    }

    const onStart = (e: TouchEvent) => {
      if (e.touches.length !== 1) return
      const touch = e.touches[0]
      startX = lastX = prevX = touch.clientX
      startY = touch.clientY
      lastAt = prevAt = performance.now()
      horizontal = null
      active = true
      armed = false
      didDrag = false
      el.style.transition = 'none'
    }

    const onMove = (e: TouchEvent) => {
      if (!active || horizontal === false) return
      const touch = e.touches[0]
      const dx = touch.clientX - startX
      const dy = touch.clientY - startY

      if (horizontal === null) {
        if (Math.abs(dx) < SLOP && Math.abs(dy) < SLOP) return
        horizontal = Math.abs(dx) > Math.abs(dy)
        if (!horizontal) return
      }

      didDrag = true
      prevX = lastX
      prevAt = lastAt
      lastX = touch.clientX
      lastAt = performance.now()
      if (e.cancelable) e.preventDefault()
      paint(dx)
    }

    const onEnd = () => {
      if (!active) return
      const wasHorizontal = horizontal === true
      active = false
      horizontal = null

      settle()

      if (!wasHorizontal) return

      const dx = lastX - startX
      const dt = Math.max(1, lastAt - prevAt)
      const velocity = (lastX - prevX) / dt

      if (shouldCommitRowSwipe(dx, velocity)) {
        haptic.medium()
        const isRtl = dirSign() === -1
        // در فارسی / RTL جابجایی منفی یعنی از راست به چپ (Start to End)
        // در انگلیسی / LTR جابجایی مثبت یعنی از چپ به راست (Start to End)
        const isStartToEnd = isRtl ? dx < 0 : dx > 0
        if (isStartToEnd) {
          handlers.current.onStartToEnd?.()
        } else {
          handlers.current.onEndToStart?.()
        }
      }

      if (didDrag) {
        const swallow = (click: Event) => {
          click.preventDefault()
          click.stopPropagation()
        }
        el.addEventListener('click', swallow, { capture: true, once: true })
        setTimeout(() => el.removeEventListener('click', swallow, { capture: true }), 350)
      }
    }

    el.addEventListener('touchstart', onStart, { passive: true })
    el.addEventListener('touchmove', onMove, { passive: false })
    el.addEventListener('touchend', onEnd)
    el.addEventListener('touchcancel', onEnd)

    return () => {
      el.removeEventListener('touchstart', onStart)
      el.removeEventListener('touchmove', onMove)
      el.removeEventListener('touchend', onEnd)
      el.removeEventListener('touchcancel', onEnd)
    }
  }, [enabled])

  return targetRef
}
