import { useEffect, useRef } from 'react'
import { haptic } from './native'

/**
 * کشیدنِ شیت با انگشت برای بستنش.
 *
 * تفاوتِ «وب‌سایت داخل اپ» و «اپ» بیشتر از هر چیزی همین‌جاست: شیتی که فقط با
 * دکمه‌ی ضربدر بسته می‌شود مثل یک مودالِ وب حس می‌شود، و شیتی که زیرِ انگشت
 * حرکت می‌کند و با سرعتِ پرتاب بسته می‌شود مثل یک اپ.
 *
 * سه چیز که پیاده‌سازی‌های ساده‌ی این ژست معمولاً غلط دارند و اینجا حل شده‌اند:
 *
 *  ۱. **دعوا با اسکرول.** محتوای شیت خودش اسکرول دارد. اگر هر کشیدنی شیت را
 *     ببرد، دیگر نمی‌شود صفِ پخش را پایین اسکرول کرد. پس کشیدن فقط از دستگیره
 *     همیشه کار می‌کند، و از خودِ محتوا تنها وقتی که اسکرول در بالاترین نقطه
 *     است — دقیقاً مثل شیت‌های سیستمی.
 *  ۲. **شنونده‌ی passive.** ری‌اکت رویدادهای لمسی را passive ثبت می‌کند و آنجا
 *     `preventDefault` بی‌اثر است — یعنی مرورگر هم‌زمان صفحه را اسکرول می‌کرد.
 *     برای همین شنونده‌ها دستی و با `passive: false` بسته می‌شوند.
 *  ۳. **سرعت، نه فقط مسافت.** یک پرتابِ کوتاه و سریع باید ببندد، و یک کشیدنِ
 *     آهسته‌ی بلند نباید. تصمیم از هر دو گرفته می‌شود.
 */

/** از این فاصله به بعد (پیکسل) دیگر معلوم است که کشیدن است نه لمسِ ساده */
const SLOP = 8
/** بسته می‌شود اگر بیش از این کشیده شود… */
const DISTANCE = 120
/** …یا با این سرعت (پیکسل بر میلی‌ثانیه) رها شود */
const VELOCITY = 0.5

/**
 * نزدیک‌ترین جدِ اسکرول‌شدنیِ نود — تا خودِ شیت بالا می‌رود و بیرون از آن
 * نمی‌گردد.
 *
 * این تابع برای این لازم شد که شیت دیگر خودش اسکرول نمی‌کند: نمای «در حال
 * پخش» یک ستونِ flexِ ثابت است و فقط پنل‌های داخلش (متن آهنگ، صف) اسکرول
 * دارند. بررسیِ `sheet.scrollTop > 0` که قبلاً کافی بود، حالا همیشه صفر است
 * و ژست را روی اسکرولِ متن می‌انداخت — کاربر انگشتش را روی متن می‌کشید و
 * به‌جای خواندنِ خط‌های بعدی، کلِ پخش‌کننده بسته می‌شد.
 */
export function scrollableAncestor(target: EventTarget | null, boundary: HTMLElement): HTMLElement | null {
  let el = target instanceof Element ? target : null
  while (el && el !== boundary) {
    const html = el as HTMLElement
    const scrollableY = html.scrollHeight - html.clientHeight
    if (scrollableY > 1 && /(auto|scroll|overlay)/.test(getComputedStyle(html).overflowY)) {
      return html
    }
    el = el.parentElement
  }
  return null
}

interface Options {
  onClose: () => void
  /** روی دسکتاپ شیت وسطِ صفحه است و کشیدن معنا ندارد */
  enabled?: boolean
}

export function useSheetDrag({ onClose, enabled = true }: Options) {
  const sheet = useRef<HTMLDivElement>(null)
  const handle = useRef<HTMLDivElement>(null)
  const backdrop = useRef<HTMLDivElement>(null)
  const close = useRef(onClose)
  close.current = onClose

  useEffect(() => {
    const el = sheet.current
    if (!el || !enabled) return

    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches

    let startY = 0
    let startedAt = 0
    /* دو نمونه‌ی آخر — سرعت از همین‌ها درمی‌آید، نه از کلِ مسیر */
    let lastY = 0
    let lastAt = 0
    let prevY = 0
    let prevAt = 0
    let offset = 0
    /** null یعنی هنوز تصمیم نگرفته‌ایم کشیدن است یا اسکرول */
    let dragging: boolean | null = null
    let fromHandle = false
    /**
     * ناحیه‌ی اسکرول‌شدنیِ زیرِ انگشت، یا null اگر لمس بیرون از چنین ناحیه‌ای
     * بوده. تا وقتی این بالا نرفته، ژستِ بستن از محتوا شروع نمی‌شود.
     */
    let scroller: HTMLElement | null = null

    const paint = (value: number) => {
      el.style.transform = `translateY(${value}px)`
      if (!backdrop.current) return
      // پس‌زمینه هم‌زمان کم‌رنگ می‌شود: بدون آن، شیت پایین می‌رود ولی صفحه
      // همان‌قدر تاریک می‌ماند و حرکت نیمه‌کاره حس می‌شود
      backdrop.current.style.opacity = String(Math.max(0, 1 - value / (DISTANCE * 3)))
    }

    const release = (dismiss: boolean) => {
      el.style.transition = reduced ? 'none' : 'transform 0.3s cubic-bezier(0.22, 1, 0.36, 1)'
      if (backdrop.current) {
        backdrop.current.style.transition = reduced ? 'none' : 'opacity 0.3s ease'
      }

      if (!dismiss) {
        paint(0)
        return
      }

      haptic.tap()
      el.style.transform = `translateY(${el.offsetHeight}px)`
      if (backdrop.current) backdrop.current.style.opacity = '0'
      // بستن بعد از پایانِ انیمیشن، نه هم‌زمان با شروعش — وگرنه شیت وسطِ
      // حرکت ناپدید می‌شود و همان پرشی می‌شود که ژست می‌خواست نباشد
      window.setTimeout(() => close.current(), reduced ? 0 : 280)
    }

    const onStart = (e: TouchEvent) => {
      if (e.touches.length !== 1) return
      const touch = e.touches[0]
      fromHandle = Boolean(handle.current?.contains(e.target as Node))
      scroller = fromHandle ? null : scrollableAncestor(e.target, el)
      // از محتوا فقط وقتی که چیزی برای اسکرول‌کردن به بالا نمانده — و آن
      // «محتوا» حالا خودِ شیت نیست، پنلِ اسکرول‌شدنیِ زیرِ انگشت است
      if (!fromHandle && scroller && scroller.scrollTop > 0) return

      startY = lastY = prevY = touch.clientY
      startedAt = lastAt = prevAt = performance.now()
      offset = 0
      dragging = null
      el.style.transition = 'none'
      el.style.animation = 'none'
      if (backdrop.current) backdrop.current.style.transition = 'none'
    }

    const onMove = (e: TouchEvent) => {
      if (dragging === false || !startedAt) return
      const touch = e.touches[0]
      const dy = touch.clientY - startY

      if (dragging === null) {
        if (Math.abs(dy) < SLOP) return
        /*
         * کشیدن به بالا از داخلِ محتوا یعنی «می‌خواهم اسکرول کنم». از دستگیره
         * ولی چیزی برای اسکرول نیست، پس همان‌جا هم کشیدن است (که با کش‌آمدن
         * پاسخ می‌گیرد، نه با هیچی).
         */
        if (dy < 0 && !fromHandle) {
          dragging = false
          return
        }
        dragging = true
      }

      // کشیدن به بالا کش می‌آید نه اینکه جواب ندهد — «تا ته رسیده» را با
      // مقاومت نشان می‌دهد، همان کاری که اسکرولِ لاستیکیِ سیستم می‌کند
      offset = dy > 0 ? dy : dy * 0.2
      prevY = lastY
      prevAt = lastAt
      lastY = touch.clientY
      lastAt = performance.now()
      // اینجاست که اسکرولِ هم‌زمانِ مرورگر متوقف می‌شود
      if (e.cancelable) e.preventDefault()
      paint(offset)
    }

    const onEnd = () => {
      if (!startedAt) return
      const wasDragging = dragging === true
      startedAt = 0
      dragging = null
      if (!wasDragging) return

      // سرعتِ لحظه‌ی رهاکردن، نه میانگینِ کلِ حرکت: کشیدنِ آهسته‌ی طولانی که
      // آخرش پرتاب می‌شود باید ببندد، و کشیدنِ بلندی که وسطِ راه متوقف شده نه
      const velocity = (lastY - prevY) / Math.max(1, lastAt - prevAt)
      release(offset > DISTANCE || velocity > VELOCITY)
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

  return { sheet, handle, backdrop }
}
