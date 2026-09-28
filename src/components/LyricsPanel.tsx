import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { engine } from '../lib/audioEngine'
import { useI18n } from '../lib/i18n'
import {
  activeLyricIndex,
  activeWordIndex,
  lineEndTime,
  lineProgress,
  wordProgress,
  type LyricLine,
} from '../lib/lrc'
import { haptic } from '../lib/native'
import { InstrumentalIcon, SyncLyricsIcon } from './icons'

/**
 * نمای کارائوکه‌ی متن آهنگ.
 *
 * چهار چیز این را از «متنِ هایلایت‌شده‌ی» قبلی جدا می‌کند:
 *
 *  ۱. **متنِ کامل، پیوسته.** همه‌ی خط‌ها یک‌جا رندر می‌شوند؛ هیچ پنجره‌ی
 *     برشی وسط متن نیست و کاربر می‌تواند بالا و پایینِ آهنگ را ببیند و
 *     اسکرول کند.
 *
 *  ۲. **پیشرویِ کلمه‌به‌کلمه.** LRC استاندارد فقط زمانِ *شروعِ خط* را دارد،
 *     پس پیشرفتِ داخلِ خط را از خودِ آهنگ می‌گیریم: خطِ فعلی تا خطِ بعدی
 *     فرصت دارد و رنگ روی کلمه‌ها به همان اندازه کشیده می‌شود. اگر فایل،
 *     LRC تقویت‌شده با تگ‌های ‎<mm:ss.xx>‎ باشد، هر کلمه‌ی خطِ فعال گرادیانِ
 *     خودش را دارد و دقیقاً سرِ لحظه‌ی خودش پر می‌شود — مثلِ اپل‌موزیک.
 *     جهتِ کشیدن هم با جهتِ متن می‌آید — فارسی از راست، انگلیسی از چپ.
 *
 *  ۳. **عمق.** خط‌های بیرون از تمرکز محو (blur) و تیره‌اند؛ خطِ فعال با یک
 *     گذارِ نرم تیز و درشت می‌شود. چشم بدونِ جستجو می‌فهمد کجاست.
 *
 *  ۴. **۶۰ فریم بدونِ ۶۰ رندرِ ری‌اکت.** موقعیتِ پخش از `timeupdate` فقط
 *     چهار بار در ثانیه می‌آید — برای کشیدنِ رنگ خیلی درشت است. پس حلقه‌ی
 *     rAF زمانِ *واقعیِ* صوت را از خودِ `<audio>` می‌خواند و فقط *یک* متغیرِ
 *     CSS روی *همان یک* نودِ فعال می‌نویسد. state ری‌اکت تنها وقتی عوض می‌شود
 *     که خودِ خط عوض شده باشد.
 *
 * ژست: کلیک/انگشت روی هر خط = پرش به همان لحظه — همان کاری که اسپاتیفای
 * و اپل‌موزیک می‌کنند.
 */

/**
 * متنِ فارسی/عربی از راست خوانده می‌شود و رنگ هم باید از همان‌جا بیاید.
 * تشخیص با بازه‌ی یونیکدِ خودِ خط است نه زبانِ رابط — یک آهنگِ فارسی ممکن
 * است یک خطِ انگلیسی وسطش داشته باشد و برعکس.
 */
function isRtl(text: string): boolean {
  return /[؀-ۿݐ-ݿ]/.test(text)
}

interface Props {
  lines: LyricLine[]
  /** ثانیه — position استور؛ برای مقدارِ اولیه‌ی رنگ قبلِ اولین فریم */
  position: number
  /** ثانیه‌ی پایانِ ترک — برای کشیدنِ خطِ آخر */
  trackEnd: number
  onSeek: (seconds: number) => void
}

export default function LyricsPanel({ lines, position, trackEnd, onSeek }: Props) {
  const { t } = useI18n()
  const scrollRef = useRef<HTMLDivElement>(null)
  const lineRefs = useRef<(HTMLParagraphElement | null)[]>([])
  /** خطِ فعالِ رندرشده؛ حلقه‌ی rAF این را با زمانِ واقعیِ صوت به‌روز می‌کند */
  const [active, setActive] = useState(() => activeLyricIndex(lines, engine.currentTime()))

  // با تعویض ترک (آرایه‌ی جدید) ایندکس از سر حساب می‌شود
  useEffect(() => {
    setActive(activeLyricIndex(lines, engine.currentTime()))
  }, [lines])

  /*
   * حلقه‌ی زمانِ واقعی.
   *
   * در حالتِ خط‌به‌خط: متغیرِ `--p` روی نودِ خطِ فعال. در حالتِ کلمه‌به‌کلمه:
   * متغیرِ `--wp` روی نودِ *کلمه‌ی* فعال (خطِ فعال را هم که `--p` می‌گیرد
   * تا گذارِ blur→sharp فارغ از حالت کار کند). نوشتنِ مستقیمِ DOM عمدی است:
   * شصت setState در ثانیه کلِ شیت را رندر می‌کرد و روی گوشی‌های میان‌رده
   * همان باعثِ لگِ محسوس می‌شد.
   */
  useEffect(() => {
    if (lines.length === 0) return
    let raf = 0
    let last = -2
    /** ایندکسِ کلمه‌ی فعالِ فریمِ قبل — تا نوشتنِ spanها فقط با تعویضِ کلمه */
    let lastWord = -2

    const tick = () => {
      const now = engine.currentTime()
      const idx = activeLyricIndex(lines, now)
      const line = lineRefs.current[idx]
      if (line) {
        const words = idx >= 0 && idx < lines.length ? lines[idx].words : undefined
        if (!words) {
          line.style.setProperty('--p', String(lineProgress(lines, idx, now, trackEnd)))
        } else {
          // خطِ کلمه‌ای: `--p` خط کامل می‌ماند تا گرادیانِ پشتیبانِ خط همیشه
          // سرِ جایش باشد؛ پرشدنِ واقعی کارِ `--wp` روی هر span است
          line.style.setProperty('--p', '1')
          const w = activeWordIndex(words, now)
          if (w !== lastWord) {
            // با تعویضِ کلمه (یا پرش به عقب/جلو) همه‌ی spanها را یکجا
            // منظم کن: قبل از w پر، بعد از w خالی — صفحه‌قلمِ هر فریم فقط
            // همین لحظه است، پس این حلقه چند بار در خط رخ می‌دهد نه هر فریم
            const spans = line.querySelectorAll<HTMLElement>('[data-word]')
            for (let i = 0; i < spans.length; i++) {
              spans[i].style.setProperty('--wp', i < w ? '1' : '0')
              if (i === w) {
                spans[i].setAttribute('data-active-word', 'true')
              } else {
                spans[i].removeAttribute('data-active-word')
              }
            }
            lastWord = w
          }
          if (w >= 0) {
            const node = line.querySelectorAll<HTMLElement>('[data-word]')[w]
            node?.style.setProperty(
              '--wp',
              String(wordProgress(words, w, now, lineEndTime(lines, idx, trackEnd))),
            )
          }
        }
      }
      if (idx !== last) {
        if (last >= 0 && lineRefs.current[last]) {
          const oldSpans = lineRefs.current[last]?.querySelectorAll<HTMLElement>('[data-active-word]')
          oldSpans?.forEach((s) => s.removeAttribute('data-active-word'))
        }
        lastWord = -2
        last = idx
        setActive(idx)
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [lines, trackEnd])

  // وضعیت اسکرول دستی توسط کاربر جهت نمایش دکمه شناور همگام‌سازی (TIDAL Floating Sync Button)
  const [userScrolled, setUserScrolled] = useState(false)
  const scrollTimeoutRef = useRef<number | null>(null)

  const handleUserInteraction = () => {
    setUserScrolled(true)
    if (scrollTimeoutRef.current) window.clearTimeout(scrollTimeoutRef.current)
    scrollTimeoutRef.current = window.setTimeout(() => {
      setUserScrolled(false)
    }, 7000)
  }

  const scrollToActive = () => {
    const pane = scrollRef.current
    const line = lineRefs.current[active]
    if (!pane || !line) return
    const target = line.offsetTop + line.offsetHeight / 2 - pane.clientHeight / 2
    pane.scrollTo({ top: Math.max(0, target), behavior: 'smooth' })
    setUserScrolled(false)
  }

  /*
   * خطِ فعال وسطِ پنل بماند — اگر کاربر اسکرول دستی نکرده باشد.
   */
  useEffect(() => {
    if (userScrolled) return
    const pane = scrollRef.current
    const line = lineRefs.current[active]
    if (!pane || !line) return
    const target = line.offsetTop + line.offsetHeight / 2 - pane.clientHeight / 2
    pane.scrollTo({ top: Math.max(0, target), behavior: 'smooth' })
  }, [active, userScrolled])

  return (
    <div className="relative size-full overflow-hidden">
      <div
        ref={scrollRef}
        onWheel={handleUserInteraction}
        onTouchMove={handleUserInteraction}
        onPointerDown={handleUserInteraction}
        className="lyrics-scroll scroll-pane no-scrollbar absolute inset-0 overflow-y-auto px-4 sm:px-8 py-3 select-none"
      >
        <div className="space-y-6 sm:space-y-8 py-16 px-2">
          {lines.map((line, index) => {
            const isActive = index === active
            const distance = Math.abs(index - active)

            const styleObj: CSSProperties = isActive
              ? ({
                  '--p': lineProgress(lines, index, position, trackEnd),
                  opacity: 1,
                } as CSSProperties)
              : ({
                  opacity: distance === 1 ? 0.45 : distance === 2 ? 0.38 : 0.28,
                } as CSSProperties)

            return (
              <p
                key={index}
                ref={(el) => {
                  lineRefs.current[index] = el
                }}
                dir={isRtl(line.text) ? 'rtl' : 'ltr'}
                role="button"
                tabIndex={0}
                aria-label={t.lyricSeekTo}
                aria-current={isActive ? 'true' : undefined}
                onClick={() => {
                  haptic.tap()
                  setUserScrolled(false)
                  onSeek(line.time)
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    setUserScrolled(false)
                    onSeek(line.time)
                  }
                }}
                style={styleObj}
                className={`karaoke-line cursor-pointer text-2xl sm:text-3xl lg:text-4xl font-extrabold leading-snug sm:leading-tight outline-none transition-[opacity,color] duration-300 focus-visible:ring-2 focus-visible:ring-white/40 ${
                  isActive
                    ? 'karaoke-active text-white'
                    : 'text-white/40 hover:text-white/60'
                }`}
              >
                {renderContent(line, isActive)}
              </p>
            )
          })}
        </div>
      </div>

      {/* دکمه شناور بازگشت به خط در حال پخش به سبک TIDAL */}
      {userScrolled && active >= 0 && (
        <button
          onClick={() => {
            haptic.tap()
            scrollToActive()
          }}
          aria-label={t.nowPlayingView}
          title="همگام‌سازی با خط در حال پخش"
          className="absolute end-4 sm:end-6 bottom-4 sm:bottom-6 z-30 grid size-12 sm:size-14 place-items-center rounded-full bg-white text-black shadow-2xl transition hover:scale-105 active:scale-95 cursor-pointer animate-in fade-in zoom-in-95 duration-200"
        >
          <SyncLyricsIcon className="size-6 text-black" />
        </button>
      )}
    </div>
  )
}

/**
 * محتوای خط: در حالتِ کلمه‌ای، هر کلمه یک `span` با گرادیانِ خودش؛ در حالتِ
 * عادی کلِ متن یک‌جا. `isActive=false` یعنی خطِ محو — کلمه‌ها بدونِ span
 * رندر می‌شوند تا DOM سبک بماند.
 */
function renderContent(line: LyricLine, isActive: boolean): ReactNode {
  const trimmed = line.text?.trim() ?? ''
  const isInst = !trimmed || trimmed === '♪' || trimmed === '...' || trimmed === '…' || /^\s*\[.*(music|instrumental|solo|outro|intro).*\]\s*$/i.test(trimmed)

  if (isInst) {
    return (
      <span className="inline-flex items-center gap-2 py-1">
        <InstrumentalIcon className={`size-5 transition-all duration-300 ${isActive ? 'animate-pulse text-white scale-110' : 'text-white/40'}`} />
      </span>
    )
  }

  if (!line.words || !isActive) return line.text
  return line.words.map((w, i) => (
    <span key={i} data-word className="karaoke-word" style={{ '--wp': 0 } as CSSProperties}>
      {w.text}
    </span>
  ))
}
