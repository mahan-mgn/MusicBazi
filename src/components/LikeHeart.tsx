import { useCallback, useRef } from 'react'
import { haptic } from '../lib/native'
import { HeartIcon } from './icons'

/** فاصله‌ی پاششِ نقطه‌ها (پیکسل) — هم‌خوان با منطقِ `seedParticles` */
const DIST = 20

interface LikeHeartProps {
  /** وضعیتِ لایک از بیرون می‌آید (استورِ favorites)، نه useState داخلی */
  liked: boolean
  onToggle: () => void
  /** کلاس‌های خودِ دکمه (اندازه/رنگ/هاور) — رنگِ قلب از همین‌جا می‌آید */
  className?: string
  iconClassName?: string
  ariaLabel: string
  title?: string
}

/**
 * قلبِ لایک با انیمیشنِ pop و پاششِ ۸ نقطه — نمونه از transitions.dev،
 * درون‌ریزی‌شده با تمِ اپ: رنگ از `--danger`، وضعیت از بیرون، pop روی لفافِ
 * HTML نه خودِ svg (وگرنه Chromium در hi-DPI پیکسلی‌اش می‌کند).
 *
 * پاشش فقط موقعِ *لایک* اجرا می‌شود نه برداشتن — همان رفتارِ نمونه. هر پاشش
 * بردار/سرعت/تأخیر/اندازه‌ی هر نقطه را دوباره تصادفی می‌کند تا تکراری دیده
 * نشود. CSS-اش در index.css است (`.like-heart`)، نه تزریقِ `<style>` در اجرا.
 */
export default function LikeHeart({
  liked,
  onToggle,
  className,
  iconClassName,
  ariaLabel,
  title,
}: LikeHeartProps) {
  const ref = useRef<HTMLButtonElement>(null)

  const seedParticles = useCallback(() => {
    const dots = ref.current?.querySelectorAll<HTMLElement>('.like-particles i')
    if (!dots) return
    dots.forEach((dot, i) => {
      const angle = (360 / dots.length) * i + (Math.random() * 2 - 1) * 16
      const mag = DIST * (0.68 + Math.random() * 0.5)
      const rad = (angle * Math.PI) / 180
      const s = dot.style
      s.setProperty('--px', `${(Math.cos(rad) * mag).toFixed(2)}px`)
      s.setProperty('--py', `${(Math.sin(rad) * mag).toFixed(2)}px`)
      s.setProperty('--pdur', `calc(var(--like-particle-dur) * ${(0.78 + Math.random() * 0.44).toFixed(3)})`)
      s.setProperty('--pdelay', `${Math.round(Math.random() * 70)}ms`)
      s.setProperty('--p-end-scale', (0.35 + Math.random() * 0.4).toFixed(2))
      s.setProperty('--psize', (0.6 + Math.random() * 0.8).toFixed(2))
    })
  }, [])

  function handleClick() {
    const el = ref.current
    if (liked) {
      // برداشتنِ لایک: پاششِ مانده پاک شود — همان رفتارِ نمونه
      el?.classList.remove('is-bursting')
      haptic.select()
      onToggle()
      return
    }
    if (el) {
      el.classList.remove('is-bursting')
      seedParticles()
      void el.offsetWidth // reflow تا پاشش از نو پخش شود
      el.classList.add('is-bursting')
      haptic.tap()
    }
    onToggle()
  }

  return (
    <button
      ref={ref}
      type="button"
      className={`like-heart ${className ?? ''}`}
      data-liked={liked ? 'true' : 'false'}
      aria-pressed={liked}
      aria-label={ariaLabel}
      title={title}
      onClick={handleClick}
    >
      <span className="like-pop">
        <HeartIcon className={iconClassName} filled={liked} />
      </span>
      <span className="like-particles" aria-hidden="true">
        {Array.from({ length: 8 }, (_, i) => (
          <i key={i} />
        ))}
      </span>
    </button>
  )
}
