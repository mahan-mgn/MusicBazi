import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../lib/i18n'
import { fetchLyricsSources, type LyricsSource } from '../lib/lyricsSources'
import type { Track } from '../lib/types'

/**
 * منوی «منبعِ متن» برای صفحهٔ Now Playing.
 *
 * دو قاعدهٔ سخت که این کامپوننت رعایت می‌کند:
 *
 *  ۱. **باز شدنِ منو هیچ Providerی را صدا نمی‌زند.** فقط
 *     `GET /api/lyrics/sources` می‌رود که سمتِ سرور تضمین شده هیچ درخواستی
 *     به Provider نمی‌فرستد. واکشیِ متن فقط بعد از انتخابِ کاربر و برای
 *     **همان یک منبع** انجام می‌شود.
 *  ۲. **منابعِ غیرقابلِ‌استفاده حذف نمی‌شوند.** خاکستری می‌شوند و علتشان
 *     نوشته می‌شود؛ «نبودنشان» یعنی کاربر نمی‌فهمد چرا نیستند.
 */

interface Props {
  track: Track
  /** منبعِ فعلاً نمایش‌داده‌شده؛ `null` یعنی «خودکار». */
  current: string | null
  /** انتخابِ منبع؛ رشتهٔ خالی یعنی بازگشت به «خودکار». */
  onSelect: (provider: string) => void
  /** تلاشِ دوباره برای همان منبعِ فعلی (با force در سمتِ سرور). */
  onRetry?: () => void
  disabled?: boolean
}

/** برچسبِ وضعیت به کلیدِ i18n — متن از دیکشنری می‌آید نه سخت‌کد. */
const STATUS_KEY: Record<string, string> = {
  available: 'srcAvailable',
  cached: 'srcCached',
  empty: 'srcEmpty',
  error: 'srcError',
  needs_setup: 'srcNeedsSetup',
  disabled: 'srcDisabled',
  blocked: 'srcBlocked',
}

/**
 * برچسبِ وضعیتِ یک منبع از دیکشنری.
 *
 * عمداً از یک جدولِ صریح می‌آید نه دسترسیِ پویا: بعضی کلیدهای دیکشنری
 * *تابع*‌اند (`(n) => string`) و رندر کردنشان به‌عنوان ReactNode خطای نوع
 * می‌دهد.
 */
function statusLabel(t: Record<string, unknown>, status: string): string {
  const key = STATUS_KEY[status] ?? 'srcAvailable'
  const value = t[key]
  return typeof value === 'string' ? value : ''
}

export default function LyricsSourceMenu({ track, current, onSelect, onRetry, disabled }: Props) {
  const t = useI18n((s) => s.t)
  const [open, setOpen] = useState(false)
  const [sources, setSources] = useState<LyricsSource[] | null>(null)
  const [unavailable, setUnavailable] = useState<LyricsSource[]>([])
  // `idle` قبلِ اولین بارگذاری، بعد loading/ready/error/empty
  const [loadState, setLoadState] = useState<'idle' | 'loading' | 'ready' | 'error' | 'empty'>(
    'idle',
  )
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const [rect, setRect] = useState<{ top: number; left: number; right: number } | null>(null)

  /**
   * بارگذاریِ فهرستِ منابع.
   *
   * حالت‌ها عمداً صریح‌اند: اگر درخواست شکست بخورد یا فهرست خالی باشد، منو
   * باید **پیام نشان بدهد**، نه اینکه بی‌صدا خالی بماند. قبلاً هر دو حالت
   * یک «منوی خالی» بود و کاربر فکر می‌کرد دکمه کار نمی‌کند.
   */
  const load = useCallback(async () => {
    setLoadState('loading')
    const body = await fetchLyricsSources(track)
    if (body === null) {
      // F6: فقط در حالتِ توسعه، و فقط کدِ وضعیت/نوع — بدونِ دادهٔ حساس
      if (import.meta.env?.DEV) {
        console.warn('[lyrics] source list request failed (network or non-200)')
      }
      setSources(null)
      setUnavailable([])
      setLoadState('error')
      return
    }
    const usable = body.sources.filter((s) => s.selectable)
    setSources(usable)
    setUnavailable(body.sources.filter((s) => !s.selectable))
    setLoadState(usable.length > 0 ? 'ready' : 'empty')
  }, [track])

  /**
   * مختصاتِ منو از خودِ دکمه.
   *
   * منو داخلِ درختِ NowPlaying نمی‌ماند: ریشهٔ آن `overflow-hidden` است و
   * منویی با ۱۲ منبع (~۴۵۰ پیکسل) بریده می‌شد. با `createPortal` به
   * `document.body` می‌رود و `position: fixed` می‌گیرد، پس هیچ والدِ
   * بریده‌شونده‌ای رویش اثر ندارد.
   *
   * از `bottom` استفاده می‌شود نه `top`: منو **بالای** دکمه باز می‌شود
   * (کنترلِ منبع پایینِ پنلِ متن است).
   */
  const place = useCallback(() => {
    const trigger = triggerRef.current
    if (!trigger) return
    const r = trigger.getBoundingClientRect()
    setRect({ top: r.top, left: r.left, right: window.innerWidth - r.right })
  }, [])

  useLayoutEffect(() => {
    if (!open) {
      setRect(null)
      return
    }
    place()
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    return () => {
      window.removeEventListener('resize', place)
      window.removeEventListener('scroll', place, true)
    }
  }, [open, place])

  const close = useCallback(() => setOpen(false), [])

  // Escape می‌بندد و فوکوس را به دکمه برمی‌گرداند
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        close()
        triggerRef.current?.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, close])

  // کلیکِ بیرون می‌بندد — با احتسابِ اینکه منو بیرونِ درخت است
  useEffect(() => {
    if (!open) return
    const onDown = (e: PointerEvent) => {
      const target = e.target as Node
      if (menuRef.current?.contains(target) || triggerRef.current?.contains(target)) return
      close()
    }
    document.addEventListener('pointerdown', onDown)
    return () => document.removeEventListener('pointerdown', onDown)
  }, [open, close])

  // واکشی فقط وقتی منو باز می‌شود — و فقط یک بار در هر باز شدن.
  useEffect(() => {
    if (!open) return
    void load()
  }, [open, load])

  // با تغییرِ آهنگ، فهرستِ قبلی بی‌اعتبار می‌شود
  useEffect(() => {
    setSources(null)
    setUnavailable([])
    setLoadState('idle')
  }, [track.id])

  const label = current ? current : t.lyricsSourceAuto

  /**
   * مختصاتِ ثابتِ منو.
   *
   * `position: fixed` چون منو در `document.body` است، نه داخلِ درختِ
   * NowPlaying. منو **بالای** دکمه باز می‌شود (`bottom` از لبهٔ پایین)، که
   * با `maxHeight` ترکیب می‌شود تا در صفحه‌های کوتاه هم کامل دیده شود.
   *
   * سمتِ راست با `right` لنگر می‌اندازد (نه `left`) تا در RTL هم درست
   * بماند — دکمه در سمتِ راستِ پنل است.
   */
  const menuStyle = rect
    ? ({
        position: 'fixed',
        bottom: `${Math.max(8, window.innerHeight - rect.top + 8)}px`,
        right: `${Math.max(8, rect.right)}px`,
        maxHeight: `${Math.max(120, rect.top - 24)}px`,
      } as const)
    : ({ display: 'none' } as const)

  /** محتوای منو — بیرون از درختِ بریده‌شونده رندر می‌شود. */
  const menu = (
    <div
      ref={menuRef}
      role="menu"
      aria-label={t.lyricsSource}
      style={menuStyle}
      className="z-50 w-64 max-h-[60vh] overflow-y-auto rounded-2xl bg-black/90 p-2 shadow-2xl backdrop-blur-xl border border-white/15 space-y-1"
    >
      <button
        role="menuitemradio"
        aria-checked={current === null}
        onClick={() => {
          onSelect('')
          setOpen(false)
        }}
        className="flex w-full items-center rounded-xl px-3 py-2 text-start text-sm text-white/90 hover:bg-white/10 cursor-pointer"
      >
        <span>{t.lyricsSourceAuto}</span>
      </button>

      {loadState === 'loading' && (
        <div className="px-3 py-2 text-xs text-white/50">{t.lyricsSourceLoading}</div>
      )}

      {loadState === 'error' && (
        <div className="space-y-1 px-3 py-2">
          <div className="text-xs text-amber-300/90">{t.lyricsSourceLoadFailed}</div>
          <button
            onClick={() => void load()}
            className="rounded-lg bg-white/10 px-2 py-1 text-[11px] text-white/80 hover:bg-white/20 cursor-pointer"
          >
            {t.lyricsSourceRetry}
          </button>
        </div>
      )}

      {loadState === 'empty' && (
        <div className="px-3 py-2 text-xs text-white/50">{t.lyricsSourceNone}</div>
      )}

      {sources?.map((source) => (
        <button
          key={source.id}
          role="menuitemradio"
          aria-checked={current === source.id}
          onClick={() => {
            onSelect(source.id)
            setOpen(false)
          }}
          className="flex w-full items-center justify-between gap-2 rounded-xl px-3 py-2 text-start text-sm text-white/90 hover:bg-white/10 cursor-pointer"
        >
          <span className="flex items-center gap-2 min-w-0">
            <span className="truncate">{source.label}</span>
            {source.experimental && (
              <span className="shrink-0 rounded bg-amber-500/20 px-1.5 text-[10px] text-amber-300">
                {t.lyricsSourceExperimental}
              </span>
            )}
          </span>
          <span className="shrink-0 text-[10px] text-white/50">
            {statusLabel(t, source.status)}
          </span>
        </button>
      ))}

      {onRetry && (
        <button
          onClick={() => {
            onRetry()
            setOpen(false)
          }}
          className="w-full rounded-xl px-3 py-2 text-start text-xs text-white/70 hover:bg-white/10 cursor-pointer"
        >
          {t.lyricsSourceRetry}
        </button>
      )}

      {unavailable.length > 0 && (
        <div className="border-t border-white/10 pt-1">
          <div className="px-3 pt-1 text-[10px] uppercase text-white/40">
            {t.lyricsSourceUnusable}
          </div>
          {unavailable.map((source) => (
            <div
              key={source.id}
              className="flex items-center justify-between gap-2 px-3 py-1.5 text-xs text-white/35"
            >
              <span className="truncate">{source.label}</span>
              <span className="shrink-0 text-[10px]">
                {source.unavailable_reason === 'needs_setup'
                  ? t.srcNeedsSetup
                  : source.terms_note
                    ? t.srcBlocked
                    : source.unavailable_reason === 'disabled'
                      ? t.srcDisabled
                      : ''}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )

  return (
    <>
      <button
        ref={triggerRef}
        onClick={() => setOpen((v) => !v)}
        disabled={disabled}
        aria-label={t.lyricsSource}
        aria-haspopup="menu"
        aria-expanded={open}
        title={t.lyricsSource}
        className="flex items-center gap-1.5 rounded-full bg-white/10 px-3 py-1.5 text-xs text-white/80 hover:bg-white/20 hover:text-white transition active:scale-95 cursor-pointer disabled:opacity-40"
      >
        <span className="truncate max-w-28">{label}</span>
      </button>
      {open && typeof document !== 'undefined' && createPortal(menu, document.body)}
    </>
  )
}
