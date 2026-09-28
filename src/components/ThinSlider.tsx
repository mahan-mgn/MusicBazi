import { useCallback, useRef, useState, type CSSProperties } from 'react'
import { haptic } from '../lib/native'

export interface ThinSliderProps {
  /** مقدار فعلی (بین ۰ تا max) */
  value: number
  /** بیشینه مقدار (پیش‌فرض ۱) */
  max?: number
  /** حداقل مقدار (پیش‌فرض ۰) */
  min?: number
  /** برچسب دسترس‌پذیری */
  label?: string
  /** کال‌بک در زمان تغییر حین درگ */
  onChange?: (val: number) => void
  /** کال‌بک نهایی هنگام رها کردن اسلایدر */
  onChangeFinished?: (val: number) => void
  /** کلاس اضافی */
  className?: string
  /** آیا غیرفعال است؟ */
  disabled?: boolean
  /** فعال بودن هپتیک بر اساس تغییر ثانیه */
  enableHapticTick?: boolean
  /**
   * موج نوری رونده در طول اسلایدر (الهام‌گرفته از MixSheen در BitChord).
   * در زمان لودینگ، ترنزیشن قطعه یا وضعیت فعال اجرا می‌شود.
   */
  sheen?: boolean
  /** ارتفاع سفارشی نوار اسلایدر (مثلاً 'h-[3px]') */
  trackHeight?: string
}

/**
 * اسلایدر مویی به سبک BitChord (`ThinSlider.kt`).
 *
 * ویژگی‌ها:
 *  - کپسول مویی بدون دستگیره برجسته (No thumb knob).
 *  - ضخامت در حالت بیکار ۶ پیکسل و در زمان لمس/درگ به ۱۰ پیکسل نرم منبسط می‌شود.
 *  - پرشدگی سفید با وضوح ۹۲٪ و ریل پس‌زمینه با وضوح ۲۶٪.
 *  - ناحیه لمس نامرئی وسیع (~۳۴ پیکسل) برای واکنش سریع و آسان انگشت.
 */
export default function ThinSlider({
  value,
  max = 1,
  min = 0,
  label = 'Slider',
  onChange,
  onChangeFinished,
  className = '',
  disabled = false,
  enableHapticTick = false,
  sheen = false,
  trackHeight,
}: ThinSliderProps) {
  const barRef = useRef<HTMLDivElement>(null)
  const [dragging, setDragging] = useState(false)
  const [dragFraction, setDragFraction] = useState<number | null>(null)
  const lastTickSecond = useRef(-1)

  const range = max - min
  const effectiveValue = dragFraction !== null ? min + dragFraction * range : value
  const progressPct = range > 0 ? Math.min(100, Math.max(0, ((effectiveValue - min) / range) * 100)) : 0

  const calculateFraction = useCallback(
    (clientX: number) => {
      if (!barRef.current) return 0
      const rect = barRef.current.getBoundingClientRect()
      if (rect.width <= 0) return 0
      const offset = clientX - rect.left
      return Math.min(1, Math.max(0, offset / rect.width))
    },
    [],
  )

  const handlePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (disabled) return
    try {
      e.currentTarget.setPointerCapture(e.pointerId)
    } catch {}
    setDragging(true)
    const frac = calculateFraction(e.clientX)
    setDragFraction(frac)
    const val = min + frac * range
    if (enableHapticTick) {
      lastTickSecond.current = Math.floor(val)
      haptic.tap()
    }
    onChange?.(val)
  }

  const handlePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragging || disabled) return
    const frac = calculateFraction(e.clientX)
    setDragFraction(frac)
    const val = min + frac * range
    if (enableHapticTick) {
      const sec = Math.floor(val)
      if (sec !== lastTickSecond.current) {
        lastTickSecond.current = sec
        haptic.select()
      }
    }
    onChange?.(val)
  }

  const handlePointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragging) return
    try {
      e.currentTarget.releasePointerCapture(e.pointerId)
    } catch {}
    const frac = calculateFraction(e.clientX)
    const finalVal = min + frac * range
    setDragging(false)
    setDragFraction(null)
    onChangeFinished?.(finalVal)
    onChange?.(finalVal)
  }

  const handlePointerCancel = (e: React.PointerEvent<HTMLDivElement>) => {
    try {
      e.currentTarget.releasePointerCapture(e.pointerId)
    } catch {}
    setDragging(false)
    setDragFraction(null)
  }

  // پشتیبانی از کلیدهای جهت‌نما در فوکوس کیبورد
  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (disabled) return
    const step = range / 20
    let nextVal: number | null = null
    if (e.key === 'ArrowRight' || e.key === 'ArrowUp') {
      nextVal = Math.min(max, effectiveValue + step)
    } else if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') {
      nextVal = Math.max(min, effectiveValue - step)
    }
    if (nextVal !== null) {
      e.preventDefault()
      onChange?.(nextVal)
      onChangeFinished?.(nextVal)
    }
  }

  return (
    <div
      role="slider"
      aria-label={label}
      aria-valuemin={min}
      aria-valuemax={max}
      aria-valuenow={effectiveValue}
      tabIndex={disabled ? -1 : 0}
      onKeyDown={handleKeyDown}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerCancel={handlePointerCancel}
      className={`group relative flex items-center h-8 sm:h-9 touch-none select-none cursor-pointer ${
        disabled ? 'opacity-40 cursor-not-allowed pointer-events-none' : ''
      } ${className}`}
      dir="ltr"
    >
      {/* ریل اسلایدر مویی */}
      <div
        ref={barRef}
        className={`relative w-full rounded-full bg-white/[0.22] overflow-hidden transition-[height] duration-200 ease-out ${
          dragging ? (trackHeight ? 'h-[5px]' : 'h-[10px]') : (trackHeight ? trackHeight : 'h-[6px] group-hover:h-[8px]')
        }`}
      >
        {/* نوار پرشدگی سفید با ۹۲٪ شفافیت — شتاب‌یافته با GPU بدون لگ ری‌فلو */}
        <div
          className={`absolute inset-y-0 left-0 w-full origin-left rounded-full bg-white/[0.92] will-change-transform ${
            dragging ? 'transition-none' : 'transition-transform duration-100 ease-out'
          }`}
          style={{ transform: `scaleX(${progressPct / 100})` } as CSSProperties}
        />
        {/* نوار هایلایت نوری شین متحرک (BitChord MixSheen) */}
        {sheen && (
          <div
            className="slider-sheen absolute inset-y-0 left-0 pointer-events-none"
            aria-hidden="true"
          />
        )}
      </div>
    </div>
  )
}
