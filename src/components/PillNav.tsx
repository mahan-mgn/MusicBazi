import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { gsap } from 'gsap'
import { reducedMotion } from '../lib/motion'

/**
 * ناوبریِ قرصی — برگرفته از reactbits.dev/components/pill-nav.
 *
 * سه چیز نسبت به نسخه‌ی اصلی عوض شده، چون نسخه‌ی اصلی برای یک صفحه‌ی لندینگِ
 * react-router نوشته شده و هیچ‌کدامِ آن فرض‌ها اینجا برقرار نیست:
 *
 * ۱. `Link` حذف شده. این اپ روتر ندارد؛ ناوبری‌اش یک `history.pushState` در
 *    `App.tsx` است. پس هر آیتم هم `href` واقعی دارد (تا کلیکِ وسط و «کپی لینک»
 *    و پیش‌نمایشِ مرورگر کار کند) و هم `onClick` که جلوی بارگذاریِ دوباره‌ی
 *    صفحه را می‌گیرد و همان ناوبریِ داخلی را صدا می‌زند.
 * ۲. ریشه‌ی کامپوننت `absolute` نیست. نسخه‌ی اصلی خودش را روی هیرو می‌انداخت؛
 *    اینجا داخلِ ردیفِ هدر می‌نشیند و باید مثل بقیه‌ی دکمه‌ها جا اشغال کند.
 * ۳. انیمیشنِ ورود از محاسبه‌ی چیدمان جدا شده. در نسخه‌ی اصلی هر دو در یک
 *    `useEffect` با وابستگیِ `items` بودند و چون `items` معمولاً آرایه‌ای است
 *    که هر رندر ساخته می‌شود، با هر رندرِ والد — اینجا: هر ضربه‌کلید در
 *    سرچ‌بارِ هدر — لوگو دوباره از صفر بزرگ می‌شد.
 *
 * رنگ‌ها پیش‌فرض از توکن‌های تم می‌آیند نه هگزِ ثابت، تا تمِ روشن و تیره هر دو
 * درست دربیایند.
 */

export type PillNavItem = {
  label: string
  href: string
  ariaLabel?: string
  /** ناوبریِ داخلی؛ اگر باشد، مرورگر خودش صفحه را عوض نمی‌کند */
  onClick?: () => void
}

export interface PillNavProps {
  /** آدرسِ تصویرِ لوگو */
  logo?: string
  /**
   * جایگزینِ `logo` برای وقتی نشانِ برند خودش SVGِ درون‌خطی است — برخلاف فایلِ
   * تصویر، رنگش را از تم می‌گیرد و در هر دو تم درست می‌ماند.
   */
  logoNode?: ReactNode
  logoAlt?: string
  logoHref?: string
  onLogoClick?: () => void
  items: PillNavItem[]
  activeHref?: string
  className?: string
  /** روی متغیرهای CSSِ همین کامپوننت می‌نشیند: `--nav-h`، `--pill-pad-x`، … */
  style?: CSSProperties
  ease?: string
  baseColor?: string
  pillColor?: string
  hoveredPillTextColor?: string
  pillTextColor?: string
  onMobileMenuClick?: () => void
  initialLoadAnimation?: boolean
  /**
   * منوی همبرگریِ موبایل. در این اپ خاموش است: مقصدهای اصلی روی گوشی در
   * `TabBar` پایینِ صفحه‌اند و دو منو برای یک مجموعه مقصد یعنی دو مسیرِ موازی
   * که باید هم‌زمان درست نگه داشته شوند.
   */
  mobileMenu?: boolean
}

export default function PillNav({
  logo,
  logoNode,
  logoAlt = 'Logo',
  logoHref,
  onLogoClick,
  items,
  activeHref,
  className = '',
  style,
  ease = 'power3.easeOut',
  baseColor = 'var(--accent)',
  pillColor = 'var(--panel)',
  hoveredPillTextColor = 'var(--accent-fg)',
  pillTextColor = 'var(--fg)',
  onMobileMenuClick,
  initialLoadAnimation = false,
  mobileMenu = true,
}: PillNavProps) {
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false)
  const circleRefs = useRef<Array<HTMLSpanElement | null>>([])
  const tlRefs = useRef<Array<gsap.core.Timeline | null>>([])
  const activeTweenRefs = useRef<Array<gsap.core.Tween | null>>([])
  const hamburgerRef = useRef<HTMLButtonElement | null>(null)
  const mobileMenuRef = useRef<HTMLDivElement | null>(null)
  const navItemsRef = useRef<HTMLDivElement | null>(null)
  const logoRef = useRef<HTMLAnchorElement | null>(null)

  /*
   * هندسه‌ی دایره‌ی هاور.
   *
   * دایره از پایینِ قرص بالا می‌آید و باید در اوجِ حرکت کلِ قرص را پر کند، پس
   * شعاعش از عرض و ارتفاعِ واقعیِ همان قرص درمی‌آید نه از یک عددِ ثابت. برای
   * همین هر بار که اندازه‌ی قرص عوض می‌شود — تغییر عرضِ پنجره، رسیدنِ فونت،
   * عوض شدنِ زبان و در نتیجه طولِ برچسب‌ها — دوباره حساب می‌شود.
   */
  useEffect(() => {
    let dead = false

    const layout = () => {
      if (dead) return
      circleRefs.current.forEach((circle, index) => {
        if (!circle?.parentElement) return

        const pill = circle.parentElement as HTMLElement
        const { width: w, height: h } = pill.getBoundingClientRect()
        if (!w || !h) return

        const R = ((w * w) / 4 + h * h) / (2 * h)
        const D = Math.ceil(2 * R) + 2
        const delta = Math.ceil(R - Math.sqrt(Math.max(0, R * R - (w * w) / 4))) + 1
        const originY = D - delta

        circle.style.width = `${D}px`
        circle.style.height = `${D}px`
        circle.style.bottom = `-${delta}px`

        gsap.set(circle, { xPercent: -50, scale: 0, transformOrigin: `50% ${originY}px` })

        const label = pill.querySelector<HTMLElement>('.pill-label')
        const hover = pill.querySelector<HTMLElement>('.pill-label-hover')

        if (label) gsap.set(label, { y: 0 })
        if (hover) gsap.set(hover, { y: Math.ceil(h + 100), opacity: 0 })

        tlRefs.current[index]?.kill()
        const tl = gsap.timeline({ paused: true })
        tl.to(circle, { scale: 1.2, xPercent: -50, duration: 2, ease, overwrite: 'auto' }, 0)
        if (label) tl.to(label, { y: -(h + 8), duration: 2, ease, overwrite: 'auto' }, 0)
        if (hover) tl.to(hover, { y: 0, opacity: 1, duration: 2, ease, overwrite: 'auto' }, 0)
        tlRefs.current[index] = tl
      })
    }

    layout()

    const onResize = () => layout()
    window.addEventListener('resize', onResize)
    // برچسب با فونتِ فالبک عرضِ دیگری دارد؛ بدون این، دایره برای قرصی حساب
    // می‌شد که هنوز وزیرمتن را ندیده بود
    document.fonts?.ready.then(layout).catch(() => {})

    const menu = mobileMenuRef.current
    if (menu) gsap.set(menu, { visibility: 'hidden', opacity: 0, scaleY: 1, y: 0 })

    return () => {
      dead = true
      window.removeEventListener('resize', onResize)
      tlRefs.current.forEach((tl) => tl?.kill())
      activeTweenRefs.current.forEach((tween) => tween?.kill())
    }
  }, [items, ease])

  // فقط یک بار، موقعِ سوار شدن — نه با هر رندرِ والد
  useEffect(() => {
    if (!initialLoadAnimation || reducedMotion()) return

    const logoEl = logoRef.current

    if (logoEl) {
      gsap.set(logoEl, { scale: 0 })
      gsap.to(logoEl, { scale: 1, duration: 0.6, ease })
    }

    /*
     * تایم‌لاینِ عرضِ ردیفِ قرص‌ها حذف شد.
     *
     * قبلاً `width` از صفر به `auto` تویین می‌شد؛ اگر این تویین وسط راه
     * می‌مرد — زمانِ مجازیِ هدلس، وسطِ تعویضِ ناظر، یا `clearProps` که به
     * پایانِ تویین گره خورده بود — یک عرضِ درون‌خطیِ نیمه روی ردیف جا
     * می‌ماند و قرصِ آخر («کتابخانه») با `overflow-hidden` بریده می‌شد.
     * ورودِ ردیف با تویینِ عرض به‌قدری شکننده بود که باگِ ظاهریِ همیشگی
     * می‌ساخت؛ نمایشِ فوریِ قرص‌ها بی‌هزینه‌تر و مطمئن‌تر است.
     */
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  /*
   * با «حرکتِ کمتر» تایم‌لاین همچنان اجرا می‌شود ولی در صفر ثانیه: کاربر
   * بازخوردِ هاور را از دست نمی‌دهد، فقط جابه‌جاییِ نرم را.
   */
  const seek = (i: number, to: number, duration: number) => {
    const tl = tlRefs.current[i]
    if (!tl) return
    activeTweenRefs.current[i]?.kill()
    activeTweenRefs.current[i] = tl.tweenTo(to, {
      duration: reducedMotion() ? 0 : duration,
      ease,
      overwrite: 'auto',
    })
  }

  const handleEnter = (i: number) => seek(i, tlRefs.current[i]?.duration() ?? 0, 0.3)
  const handleLeave = (i: number) => seek(i, 0, 0.2)

  const setMobileMenu = (open: boolean) => {
    setIsMobileMenuOpen(open)

    const hamburger = hamburgerRef.current
    const menu = mobileMenuRef.current

    if (hamburger) {
      const lines = hamburger.querySelectorAll('.hamburger-line')
      gsap.to(lines[0], { rotation: open ? 45 : 0, y: open ? 3 : 0, duration: 0.3, ease })
      gsap.to(lines[1], { rotation: open ? -45 : 0, y: open ? -3 : 0, duration: 0.3, ease })
    }

    if (menu) {
      if (open) {
        gsap.set(menu, { visibility: 'visible' })
        gsap.fromTo(
          menu,
          { opacity: 0, y: 10, scaleY: 1 },
          { opacity: 1, y: 0, scaleY: 1, duration: 0.3, ease, transformOrigin: 'top center' },
        )
      } else {
        gsap.to(menu, {
          opacity: 0,
          y: 10,
          scaleY: 1,
          duration: 0.2,
          ease,
          transformOrigin: 'top center',
          onComplete: () => gsap.set(menu, { visibility: 'hidden' }),
        })
      }
    }
  }

  const cssVars = useMemo(
    () =>
      ({
        ['--base']: baseColor,
        ['--pill-bg']: pillColor,
        ['--hover-text']: hoveredPillTextColor,
        ['--pill-text']: pillTextColor,
        ['--nav-h']: '42px',
        ['--pill-pad-x']: '18px',
        ['--pill-gap']: '3px',
        ['--pill-font']: '16px',
        ...style,
      }) as CSSProperties,
    [baseColor, pillColor, hoveredPillTextColor, pillTextColor, style],
  )

  const logoTarget = logoHref ?? items[0]?.href ?? '#'
  const logoAction = onLogoClick ?? items[0]?.onClick

  const brand = logoNode ? (
    <span
      className="grid size-full place-items-center"
      style={{ color: 'var(--hover-text)' }}
    >
      {logoNode}
    </span>
  ) : (
    <img src={logo} alt={logoAlt} className="block size-full object-contain" />
  )

  const pillClasses =
    'relative box-border inline-flex h-full cursor-pointer items-center justify-center overflow-hidden whitespace-nowrap rounded-full px-0 font-semibold leading-[0] no-underline'

  return (
    <div className={`relative ${className}`} style={cssVars}>
      <nav aria-label={logoAlt} className="box-border flex w-max items-center justify-start">
        {/*
          نشانِ برند فقط خودِ تصویر است — بدونِ پلاکِ رنگیِ پس‌زمینه و بدونِ
          بریدن به شکلِ دایره. `var(--base)` عمداً اینجا نمی‌آید: قرصِ ناوبری و
          دایره‌ی هاور از آن استفاده می‌کنند، ولی زیرِ لوگو یک لکه‌ی رنگیِ اضافه
          بود که نشان را قاب می‌گرفت. خودِ `logo-mark.png` شفاف است.
        */}
        <a
          href={logoTarget}
          aria-label={logoAlt}
          onClick={(e) => {
            if (!logoAction) return
            e.preventDefault()
            logoAction()
          }}
          ref={logoRef}
          className="inline-flex shrink-0 items-center justify-center"
          style={{ width: 'var(--nav-h)', height: 'var(--nav-h)' }}
        >
          {brand}
        </a>

        <div
          ref={navItemsRef}
          className="relative ms-2 hidden items-center rounded-full sm:flex"
          style={{ height: 'var(--nav-h)', background: 'var(--base)' }}
        >
          <ul
            role="menubar"
            className="m-0 flex h-full list-none items-stretch p-[3px]"
            style={{ gap: 'var(--pill-gap)' }}
          >
            {items.map((item, i) => (
              <li key={item.href} role="none" className="flex h-full">
                <a
                  role="menuitem"
                  href={item.href}
                  className={pillClasses}
                  style={{
                    background: 'var(--pill-bg)',
                    color: 'var(--pill-text)',
                    paddingInline: 'var(--pill-pad-x)',
                    fontSize: 'var(--pill-font)',
                  }}
                  aria-label={item.ariaLabel || item.label}
                  aria-current={activeHref === item.href ? 'page' : undefined}
                  onMouseEnter={() => handleEnter(i)}
                  onMouseLeave={() => handleLeave(i)}
                  // با تب هم همان قرص پر می‌شود؛ وگرنه کاربرِ صفحه‌کلید
                  // نمی‌فهمید کجاست
                  onFocus={() => handleEnter(i)}
                  onBlur={() => handleLeave(i)}
                  onClick={(e) => {
                    if (!item.onClick) return
                    e.preventDefault()
                    item.onClick()
                  }}
                >
                  <span
                    className="hover-circle pointer-events-none absolute bottom-0 left-1/2 z-[1] block rounded-full"
                    style={{ background: 'var(--base)', willChange: 'transform' }}
                    aria-hidden="true"
                    ref={(el) => {
                      circleRefs.current[i] = el
                    }}
                  />
                  {/*
                    برچسب دو نسخه دارد: یکی که بالا می‌رود و یکی که از پایین
                    جایش را می‌گیرد. ارتفاعِ خط صفر نیست چون فارسی زیرِ کرسی
                    نقطه و دنباله دارد و با leading-0 داخلِ قرصِ overflow-hidden
                    بریده می‌شد.
                  */}
                  <span className="label-stack relative z-[2] inline-block leading-[1.4]">
                    <span
                      className="pill-label relative z-[2] inline-block leading-[1.4]"
                      style={{ willChange: 'transform' }}
                    >
                      {item.label}
                    </span>
                    <span
                      className="pill-label-hover absolute start-0 top-0 z-[3] inline-block leading-[1.4]"
                      style={{ color: 'var(--hover-text)', willChange: 'transform, opacity' }}
                      aria-hidden="true"
                    >
                      {item.label}
                    </span>
                  </span>
                  {activeHref === item.href && (
                    <span
                      className="absolute -bottom-[6px] left-1/2 z-[4] size-3 -translate-x-1/2 rounded-full"
                      style={{ background: 'var(--base)' }}
                      aria-hidden="true"
                    />
                  )}
                </a>
              </li>
            ))}
          </ul>
        </div>

        {mobileMenu && (
          <button
            ref={hamburgerRef}
            onClick={() => {
              setMobileMenu(!isMobileMenuOpen)
              onMobileMenuClick?.()
            }}
            aria-label={logoAlt}
            aria-expanded={isMobileMenuOpen}
            className="relative ms-2 flex cursor-pointer flex-col items-center justify-center gap-1 rounded-full border-0 p-0 sm:hidden"
            style={{ width: 'var(--nav-h)', height: 'var(--nav-h)', background: 'var(--base)' }}
          >
            <span
              className="hamburger-line h-0.5 w-4 origin-center rounded"
              style={{ background: 'var(--pill-bg)' }}
            />
            <span
              className="hamburger-line h-0.5 w-4 origin-center rounded"
              style={{ background: 'var(--pill-bg)' }}
            />
          </button>
        )}
      </nav>

      {mobileMenu && (
        <div
          ref={mobileMenuRef}
          className="absolute inset-x-0 top-[calc(var(--nav-h)+8px)] z-40 origin-top rounded-[27px] shadow-xl sm:hidden"
          style={{ background: 'var(--base)' }}
        >
          <ul className="m-0 flex list-none flex-col gap-[3px] p-[3px]">
            {items.map((item) => (
              <li key={item.href}>
                <a
                  href={item.href}
                  className="block rounded-[50px] px-4 py-3 text-[16px] font-medium transition-colors"
                  style={{ background: 'var(--pill-bg)', color: 'var(--pill-text)' }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = 'var(--base)'
                    e.currentTarget.style.color = 'var(--hover-text)'
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = 'var(--pill-bg)'
                    e.currentTarget.style.color = 'var(--pill-text)'
                  }}
                  onClick={(e) => {
                    setMobileMenu(false)
                    if (!item.onClick) return
                    e.preventDefault()
                    item.onClick()
                  }}
                >
                  {item.label}
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
