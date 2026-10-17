import { useEffect, useState } from 'react'
import { useI18n } from '../lib/i18n'
import { fetchLyricsSources, type LyricsSource } from '../lib/lyricsSources'
import type { Track } from '../lib/types'
import { usePopover } from '../lib/usePopover'

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
  const box = usePopover<HTMLDivElement>(open, () => setOpen(false))

  // واکشی فقط وقتی منو باز می‌شود — و فقط یک بار در هر باز شدن.
  useEffect(() => {
    if (!open) return
    let cancelled = false
    fetchLyricsSources(track).then((body) => {
      if (cancelled || !body) return
      const usable = body.sources.filter((s) => s.selectable)
      setSources(usable)
      setUnavailable(body.sources.filter((s) => !s.selectable))
    })
    return () => {
      cancelled = true
    }
  }, [open, track.id])

  // با تغییرِ آهنگ، فهرستِ قبلی بی‌اعتبار می‌شود
  useEffect(() => {
    setSources(null)
    setUnavailable([])
  }, [track.id])

  const label = current ? current : t.lyricsSourceAuto

  return (
    <div ref={box} className="relative">
      <button
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

      {open && (
        <div
          role="menu"
          aria-label={t.lyricsSource}
          className="absolute end-0 bottom-full mb-2 z-50 w-64 rounded-2xl bg-black/90 p-2 shadow-2xl backdrop-blur-xl border border-white/15 space-y-1"
        >
          <button
            role="menuitemradio"
            aria-checked={current === null}
            onClick={() => {
              onSelect('')
              setOpen(false)
            }}
            className="flex w-full items-center justify-between rounded-xl px-3 py-2 text-start text-sm text-white/90 hover:bg-white/10 cursor-pointer"
          >
            <span>{t.lyricsSourceAuto}</span>
            <span className="text-[10px] text-white/50">{t.lyricsSourceTypeAuto}</span>
          </button>

          {sources === null ? (
            <div className="px-3 py-2 text-xs text-white/50">{t.lyricsSourceLoading}</div>
          ) : (
            sources.map((source) => (
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
            ))
          )}

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
      )}
    </div>
  )
}
