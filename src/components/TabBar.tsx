import { memo, useCallback, useEffect, useRef, useState } from 'react'
import { useI18n } from '../lib/i18n'
import { reducedMotion } from '../lib/motion'
import { haptic } from '../lib/native'
import { HomeIcon, LibraryIcon, SearchIcon, StatsIcon } from './icons'
import GlassNavBar from './GlassNavBar'
import { useSettings } from '../store/settings'

/**
 * ناوبریِ پایینِ صفحه — فقط روی گوشی.
 *
 * روی دسکتاپ همین چهار مقصد در هدر کنارِ هم‌اند و تب‌بار فقط فضا می‌گرفت. روی
 * گوشی برعکس: بالای صفحه از همه‌جا دورتر است و کاربر با یک دست نمی‌رسد بهش،
 * برای همین هر اپ موبایلیِ جدی مقصدهای اصلی‌اش را پایین می‌گذارد.
 *
 * «جستجو» عمداً صفحه‌ی جدا نیست: خودِ سرچ‌بارِ هدر با فوکوس‌شدن تاریخچه و
 * پیشنهادها را باز می‌کند، و ساختنِ یک صفحه‌ی دومِ جستجو یعنی دو مسیرِ موازی
 * که باید هم‌زمان نگه داشته شوند.
 */

export type Tab = 'home' | 'search' | 'library' | 'stats'

interface Props {
  active: Tab
  onHome: () => void
  onLibrary: () => void
  onStats: () => void
  onSearch: () => void
}

/**
 * فاصله‌ی نشانگر انتخاب از لبه‌ی هر خانه، مطابق PILL_INSET در BitChord.
 */
const LENS_PAD = 6

/** حالتِ فنرِ لنز — x موقعیتِ فعلی، v سرعت، target مقصد، origin نقطه‌ی شروعِ پرش */
export interface SpringState {
  x: number
  v: number
  target: number
  origin: number
}

/**
 * حرکت فنری لنز مطابق نوار BitChord: سختی ۳۲۰ و میرایی ۰٫۷۲؛ یک عبور نرم
 * از مقصد دارد و زود می‌نشیند.
 *
 * a = (-k·(x−target) − c·v) / m   →   v += a·dt   →   x += v·dt
 *
 * خروجی `true` یعنی نشست (همگرایی)؛ آن‌گاه دقیقاً روی target قفل می‌شود تا
 * لرزشِ باقی‌مانده جا نماند. تابع خالص است — بدون DOM — تا قابلِ تست باشد.
 */
export function integrateSpring(s: SpringState, dt: number, k = 320, c = 26): boolean {
  const a = -k * (s.x - s.target) - c * s.v
  s.v += a * dt
  s.x += s.v * dt
  if (Math.abs(s.target - s.x) < 0.4 && Math.abs(s.v) < 2) {
    s.x = s.target
    s.v = 0
    return true
  }
  return false
}

export default memo(TabBar)

function TabBar(props: Props) {
  // تب‌بار فقط موبایل است (`sm:hidden`). روی دسکتاپ بدونِ این در، کلِ رندرِ
  // ۴ تب + حلقه‌ی فنر + اندازه‌گیریِ layout بی‌مصرف اجرا می‌شد. شرطِ
  // `min-width:640px` دقیقاً معکوسِ `sm:` است (ناحیه‌ی مرده بین ۶۳۹/۶۴۰
  // ندارد) و مقدارش primitive است → رندرِ دوباره فقط با تعویضِ جهت.
  // گاردِ matchMedia مثلِ motion.ts: jsdom آن را ندارد مگر stub شود.
  const hasMM = typeof window !== 'undefined' && typeof window.matchMedia === 'function'
  const [isMobile, setIsMobile] = useState(() => !hasMM || !window.matchMedia('(min-width: 640px)').matches)
  const liquidGlass = useSettings((s) => s.liquidGlass)
  useEffect(() => {
    if (!hasMM) return
    const mq = window.matchMedia('(min-width: 640px)')
    const onChange = () => setIsMobile(!mq.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [hasMM])
  if (!isMobile) return null
  if (liquidGlass) return <GlassNavBar {...props} />
  return <TabBarInner {...props} />
}

export function TabBarInner({ active, onHome, onLibrary, onStats, onSearch }: Props) {
  // selector به‌جایِ destructuring: `{ t }` از کلِ store، هر `set`ِ بی‌ربطِ
  // آینده تب را هم می‌خواباند؛ `t` و `lang` هر دو رفرنسِ پایدارند (DICT ثابت)
  const t = useI18n((s) => s.t)
  const lang = useI18n((s) => s.lang)
  const ulRef = useRef<HTMLUListElement>(null)
  const lensRef = useRef<HTMLLIElement>(null)
  const btnRefs = useRef<Array<HTMLButtonElement | null>>([])
  const rafRef = useRef(0)
  const sizeRafRef = useRef(0)
  const springRef = useRef<SpringState>({ x: 0, v: 0, target: 0, origin: 0 })
  // اولین جای‌گذاری بدونِ انیمیشن است؛ بعد از آن تعویضِ تب فنر می‌خورد
  const didInit = useRef(false)

  const tabs = [
    { key: 'home' as const, label: t.home, Icon: HomeIcon, run: onHome },
    { key: 'search' as const, label: t.search, Icon: SearchIcon, run: onSearch },
    { key: 'library' as const, label: t.library, Icon: LibraryIcon, run: onLibrary },
    { key: 'stats' as const, label: t.stats, Icon: StatsIcon, run: onStats },
  ]
  const activeIndex = Math.max(0, tabs.findIndex((tb) => tb.key === active))

  /**
   * لنز را اندازه می‌گیرد و به خانه‌ی تبِ فعال می‌برد.
   *
   * موقعیت از `getBoundingClientRect` می‌آید، پس پیکسلِ *فیزیکی* است و در RTL
   * خود‌به‌خود درست است — برخلافِ translateXِ منطقی که در فارسی وارونه می‌شد.
   * اندازه‌ی لنز آنی ست می‌شود (تب‌ها همه هم‌عرض‌اند)؛ فقط x فنر می‌خورد.
   *
   * بی‌gsap: یک انیمیشنِ ۲۰۰ms تک‌خاصیتِ transform را `style.transform`ِ خالص
   * می‌سازد؛ gsap روی این مسیر فقط size‌ی باندل و یک لایه‌ی کتابخانه وسطِ
   * حلقه‌ی rAF اضافه می‌کرد.
   */
  const place = useCallback(
    (animate: boolean) => {
      const ul = ulRef.current
      const lens = lensRef.current
      const btn = btnRefs.current[activeIndex]
      if (!ul || !lens || !btn) return
      const u = ul.getBoundingClientRect()
      const b = btn.getBoundingClientRect()
      if (!b.width) return // هنوز چیده نشده (jsdom / قبلِ layout)

      const w = b.width - LENS_PAD * 2
      const h = b.height - LENS_PAD * 2
      const x = b.left - u.left + LENS_PAD
      // اندازه فقط وقتی عوض شده نوشته شود؛ نوشتنِ بی‌تغییری استایل = invalidate بی‌مورد
      const sw = `${w}px`, sh = `${h}px`
      if (lens.style.width !== sw) lens.style.width = sw
      if (lens.style.height !== sh) lens.style.height = sh

      const s = springRef.current
      cancelAnimationFrame(rafRef.current)
      const pose = (px: number, lift = 0, stretch = 1) => {
        // یک نوشتارِ transformِ فشرده در فریم (مجموعِ جابه‌جایی+قوس+کشش)
        lens.style.transform = `translate3d(${px}px,${-lift}px,0) scale(${stretch},${1 / stretch})`
      }
      if (!animate || reducedMotion()) {
        s.x = s.target = s.origin = x
        s.v = 0
        pose(x)
        return
      }

      s.origin = s.x
      s.target = x
      let last = performance.now()
      const tick = (now: number) => {
        // dt سقف دارد: تعویضِ تب یا بازگشت از پس‌زمینه یک جهشِ بزرگِ زمان می‌دهد
        // و بدونِ سقف، فنر منفجر می‌شود (x به بی‌نهایت پرتاب می‌شود)
        const dt = Math.min((now - last) / 1000, 1 / 30)
        last = now
        if (integrateSpring(s, dt)) {
          // نشست: قفلِ دقیق روی مقصد، بدونِ باقی‌مانده‌ی کشش/قوس — یک نوشتار
          lens.style.transform = `translate3d(${s.x}px,0,0)`
          return
        }

        // کشسانیِ حجم‌پای: هرچه سریع‌تر، کشیده‌تر.
        const vel = Math.abs(s.v) / 60
        const stretch = 1 + Math.min(vel * 0.01, 0.12)
        // قوسِ سهمیِ پرش: در میانه‌ی مسیر اوج می‌گیرد (sin(prog·π))، در دو سر صفر.
        // سقفِ 3px چون overflow-hiddenِ کپسول بیشتر را می‌بُرد.
        const span = Math.abs(s.target - s.origin) || 1
        const prog = Math.min(Math.max((s.x - s.origin) / (s.target - s.origin || 1), 0), 1)
        const lift = Math.min(span * 0.06, 3) * Math.sin(prog * Math.PI)
        pose(s.x, lift, stretch)
        rafRef.current = requestAnimationFrame(tick)
      }
      rafRef.current = requestAnimationFrame(tick)
    },
    [activeIndex],
  )

  // با هر تعویضِ تب: اولین بار آنی، بعد فنری
  useEffect(() => {
    place(didInit.current)
    didInit.current = true
  }, [place])

  // زبان: برچسب‌ها و `dir` عوض می‌شوند، کل صفحه آینه/بازچین می‌شود. فنری
  // جابه‌جا شدن وسطِ این بازچینی یعنی لنز به هدفِ منقضی‌شده پرتاب شود
  // (روی مرورگر زنده اندازه‌گیری شد: translate3d(3304px) در حالِ پرش).
  // مثلِ resize: آنی بنشیند.
  useEffect(() => {
    if (!didInit.current) return
    place(false)
  }, [lang, place])

  // تغییرِ عرضِ پنجره و رسیدنِ فونت: اندازه‌ها عوض می‌شوند، بی‌انیمیشن از نو.
  // rAF-throttled: در درگِ پنجره/چرخشِ موبایل resize ده‌ها بار می‌آید و هر بار
  // دو getBoundingClientRectِ اجباری (read بعد از نوشتنِ قبلی) یعنی layout
  // thrashing؛ حداکثر یک اندازه‌گیری در فریم.
  useEffect(() => {
    const measure = () => {
      sizeRafRef.current = 0
      place(false)
    }
    const onResize = () => {
      if (!sizeRafRef.current) sizeRafRef.current = requestAnimationFrame(measure)
    }
    window.addEventListener('resize', onResize)
    document.fonts?.ready.then(onResize).catch(() => {})
    return () => {
      window.removeEventListener('resize', onResize)
      if (sizeRafRef.current) cancelAnimationFrame(sizeRafRef.current)
    }
  }, [place])

  // پاک‌سازیِ کامل: هر دو حلقه‌ی rAF باید ببندند، وگرنه تیکِ معلق روی
  // گره‌ی جدا‌شده نوشته می‌کند (نصبِ دوباره در StrictMode این را می‌سوزاند)
  useEffect(
    () => () => {
      cancelAnimationFrame(rafRef.current)
      if (sizeRafRef.current) cancelAnimationFrame(sizeRafRef.current)
    },
    [],
  )

  return (
    <nav
      aria-label={t.brand}
      // کپسول مثلِ BitChord شناور است: خودِ nav فقط یک لایه‌ی موقعیتِ شفاف است و کپسولِ
      // شیشه‌ای داخلش با فاصله از لبه‌ها و از نوارِ خانه معلق است — محتوا از
      // زیرش رد می‌شود و بلور زنده دیده می‌شود. max(0.75rem, safe-b) یعنی روی
      // آیفونِ ناچ‌دار کپسول بالای خطِ خانه می‌نشیند، نه زیرش.
      // کپسول و ناوبر یکی شدند: `inset-x-3 + mx-auto + max-w-md` همان
      // px-3ِ قبلی را می‌دهد، و `bottom-[max(...)]` همان pb را. لازم بود چون
      // LiquidGlass شیشه را فقط از فرزندِ *مستقیمِ* ریشه می‌سازد.
      data-lg=""
      data-lg-radius="28"
      className="glass tabbar-shell fixed inset-x-3 bottom-[max(0.75rem,var(--safe-b))] z-40 mx-auto flex h-14 max-w-md items-stretch overflow-hidden rounded-full sm:hidden"
    >
      {/*
        کپسولِ شیشه‌یِ «ساکن». داخلش یک لنزِ جداگانه (li.tabbar-lens) با فنر
        بینِ تب‌ها سُر می‌خورد. لنز را به گوشه‌های گردِ کپسول می‌بُرد؛ relative
        لنگرِ مطلقِ لنز است. خودِ کپسول (شیشه‌ی WebGL) همان nav است، پس این‌جا
        دیگر `glass` نمی‌آید — شیشه‌ی تودرتو را کتابخانه رد می‌کند.
      */}
      <ul
        ref={ulRef}
        className="relative flex h-full w-full items-stretch overflow-hidden rounded-full"
      >
        <li
          ref={lensRef}
          aria-hidden="true"
          className="tabbar-lens pointer-events-none absolute top-[6px] left-0 z-0 block rounded-full"
        />
        {tabs.map(({ key, label, Icon, run }, i) => {
          const on = active === key
          return (
            <li key={key} className="relative z-10 flex-1">
              <button
                ref={(el) => {
                  btnRefs.current[i] = el
                }}
                // هپتیک روی pointerdown: با onClick تا «انگشت رفت بالا» صبر
                // می‌کرد و بازخورد یک فریم دیر می‌رسید؛ خودِ مسیریابی همان‌جا
                // (click) می‌ماند که با pointerdownِ لغزشِ انگشت دو‌بار نشود
                onPointerDown={() => {
                  if (!on) haptic.select()
                }}
                onClick={() => run()}
                aria-current={on ? 'page' : undefined}
                className="flex size-full flex-col items-center justify-center gap-1"
              >
                {/*
                  برخلافِ نسخه‌ی قدیم دیگر قرصِ رنگیِ جداگانه زیرِ هر تب نیست —
                  انتخاب را همان لنزِ سُر‌خور نشان می‌دهد (الگوی BitChord). تبِ
                  فعال فقط رنگِ اکسنت و کمی بزرگ‌نماییِ آیکون می‌گیرد تا «بلند
                  شده» به‌نظر برسد (lift در نوارِ BitChord).
                */}
                <span
                  className={`grid h-7 w-12 place-items-center rounded-full transition-transform duration-200 ${
                    on ? 'scale-[1.07] text-fg' : 'text-fg/65'
                  }`}
                >
                  <Icon className="size-5" />
                </span>
                <span
                  className={`text-[10px] leading-none transition-colors ${
                    on ? 'font-semibold text-fg' : 'text-fg/65'
                  }`}
                >
                  {label}
                </span>
              </button>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}
