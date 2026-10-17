import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../lib/i18n'
import { fetchLyricsSources, type LyricsSource } from '../lib/lyricsSources'
import { isSheetLayout, placeMenu, type Placement } from '../lib/popoverPlacement'
import type { Track } from '../lib/types'

/**
 * منوی «منبعِ متن» برای صفحهٔ Now Playing.
 *
 * سه چیز که این کامپوننت تضمین می‌کند:
 *
 *  ۱. **باز شدنش هیچ Providerی را صدا نمی‌زند** — فقط
 *     `GET /api/lyrics/sources` که سمتِ سرور تضمین شده هیچ درخواستی به
 *     Provider نمی‌فرستد.
 *  ۲. **هرگز بریده نمی‌شود.** با `createPortal` بیرون از درختِ
 *     `overflow-hidden` رندر می‌شود و موقعیتش با `placeMenu` حساب می‌شود؛
 *     اگر بالا/پایین جا نباشد، اسکرول داخلی می‌گیرد.
 *  ۳. **هیچ‌وقت بی‌صدا خالی نمی‌ماند.** بارگذاری، خطا، و خالی هرکدام پیامِ
 *     خودشان را دارند.
 *
 * در عرضِ کم، به‌جای پاپ‌اور یک شیتِ پایین می‌شود: دکمه‌های لمسی بزرگ‌اند و
 * پاپ‌اورِ باریک روی موبایل سخت لمس می‌شود.
 */

interface Props {
  track: Track
  /** منبعِ فعلاً انتخاب‌شده؛ `null` یعنی «خودکار». */
  current: string | null
  /** منبعی که واقعاً متن را داده — برای نمایش «خودکار · LRCLIB». */
  usedSource?: string | null
  /** انتخابِ منبع؛ رشتهٔ خالی یعنی بازگشت به «خودکار». */
  onSelect: (provider: string) => void
  /** تلاشِ دوباره برای همان منبعِ فعلی (با force در سمتِ سرور). */
  onRetry?: () => void
  disabled?: boolean
}

/** وضعیت → کلیدِ i18n. برچسبِ نهایی از دیکشنری می‌آید، نه سخت‌کد. */
const OUTCOME_KEY: Record<string, string> = {
  cached: 'lyricsSourceInUse',
  not_found: 'lyricsSourceNotFound',
  error: 'lyricsSourceFailedShort',
  never_tried: 'lyricsSourceNotTried',
}

const STATUS_FALLBACK: Record<string, string> = {
  available: 'Not tried',
  cached: 'In use',
  empty: 'Not found',
  error: 'Failed',
  needs_setup: 'Needs setup',
  disabled: 'Off',
  blocked: 'Unavailable',
}

function statusText(t: Record<string, unknown>, source: LyricsSource, current: string | null): string {
  // «در حال استفاده» دقیق‌تر از وضعیتِ کش است: همین حالا متن از این منبع است.
  if (source.id === current) {
    return typeof t.lyricsSourceInUse === 'string' ? t.lyricsSourceInUse : 'In use'
  }
  const key = OUTCOME_KEY[source.last_outcome ?? 'never_tried'] ?? 'lyricsSourceNotTried'
  const value = t[key]
  return typeof value === 'string' ? value : (STATUS_FALLBACK[source.status] ?? '')
}

/** برچسبِ نوعِ هم‌زمانی — کوتاه، برای نشانِ کنارِ نام. */
function capabilityTags(source: LyricsSource): string[] {
  const tags: string[] = []
  if (source.capabilities.includes('word')) tags.push('Word')
  else if (source.capabilities.includes('ttml')) tags.push('TTML')
  else if (source.capabilities.includes('line')) tags.push('Line')
  else tags.push('Plain')
  return tags
}

export default function LyricsSourceMenu({ track, current, usedSource, onSelect, onRetry, disabled }: Props) {
  const t = useI18n((s) => s.t)
  const [open, setOpen] = useState(false)
  const [sources, setSources] = useState<LyricsSource[] | null>(null)
  const [unavailable, setUnavailable] = useState<LyricsSource[]>([])
  const [showUnusable, setShowUnusable] = useState(false)
  const [loadState, setLoadState] = useState<'idle' | 'loading' | 'ready' | 'error' | 'empty'>('idle')
  const [placement, setPlacement] = useState<Placement | null>(null)
  const [sheet, setSheet] = useState(false)

  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([])

  const load = useCallback(async () => {
    setLoadState('loading')
    const body = await fetchLyricsSources(track)
    if (body === null) {
      if (import.meta.env?.DEV) {
        // فقط نوعِ خطا — نه URL، نه توکن، نه متنِ آهنگ
        console.warn('[lyrics] source list request failed')
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

  /** موقعیت را از دکمه و اندازهٔ واقعیِ منو حساب کن. */
  const reposition = useCallback(() => {
    const trigger = triggerRef.current
    const menu = menuRef.current
    if (!trigger || !menu) return
    const a = trigger.getBoundingClientRect()
    setSheet(isSheetLayout(window.innerWidth))
    setPlacement(
      placeMenu({
        anchor: { top: a.top, left: a.left, right: a.right, bottom: a.bottom, width: a.width, height: a.height },
        menu: { width: menu.offsetWidth, height: menu.scrollHeight },
        viewport: { width: window.innerWidth, height: window.innerHeight },
      }),
    )
  }, [])

  useLayoutEffect(() => {
    if (!open) {
      setPlacement(null)
      return
    }
    reposition()
    window.addEventListener('resize', reposition)
    window.addEventListener('scroll', reposition, true)
    return () => {
      window.removeEventListener('resize', reposition)
      window.removeEventListener('scroll', reposition, true)
    }
  }, [open, reposition, sources])

  useEffect(() => {
    if (!open) return
    void load()
  }, [open, load])

  useEffect(() => {
    setSources(null)
    setUnavailable([])
    setLoadState('idle')
    setShowUnusable(false)
  }, [track.id])

  const close = useCallback(() => setOpen(false), [])

  // Escape می‌بندد و فوکوس را برمی‌گرداند
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

  // کلیکِ بیرون می‌بندد
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

  /** حرکتِ فوکوس با فلش‌ها/Home/End — روی آیتم‌های منو. */
  const onMenuKeyDown = (e: React.KeyboardEvent) => {
    const items = itemRefs.current.filter(Boolean) as HTMLButtonElement[]
    if (items.length === 0) return
    const active = items.findIndex((el) => el === document.activeElement)
    let next = active
    if (e.key === 'ArrowDown') next = active < 0 ? 0 : (active + 1) % items.length
    else if (e.key === 'ArrowUp') next = active <= 0 ? items.length - 1 : active - 1
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = items.length - 1
    else return
    e.preventDefault()
    items[next]?.focus()
  }

  const label = current ? current : t.lyricsSourceAuto
  // «خودکار · LRCLIB»: هم می‌گوید حالت خودکار است، هم متن از کجا آمده.
  const triggerText =
    !current && usedSource ? t.lyricsSourceAutomaticOf(usedSource) : label

  const itemStyle = useMemo(() => {
    if (sheet) return undefined
    if (!placement) return { visibility: 'hidden' as const, position: 'fixed' as const, top: 0, left: 0 }
    return {
      position: 'fixed' as const,
      top: `${placement.top}px`,
      left: `${placement.left}px`,
      maxHeight: `${placement.maxHeight}px`,
    }
  }, [placement, sheet])

  const list = (
    <>
      <button
        role="menuitemradio"
        aria-checked={current === null}
        ref={(el) => {
          itemRefs.current[0] = el
        }}
        onClick={() => {
          onSelect('')
          setOpen(false)
        }}
        className="flex w-full items-center justify-between rounded-xl px-3 py-2 text-start text-sm text-white/90 hover:bg-white/10 focus:bg-white/10 focus:outline-none cursor-pointer"
      >
        <span>{t.lyricsSourceAuto}</span>
      </button>

      {loadState === 'loading' && (
        <div className="px-3 py-2 text-xs text-white/50">{t.lyricsSourceLoading}</div>
      )}

      {loadState === 'error' && (
        <div className="flex items-center justify-between gap-2 px-3 py-2">
          <span className="text-xs text-amber-300/90">{t.lyricsSourceLoadFailed}</span>
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

      {sources && sources.length > 0 && (
        <div className="px-3 pt-1 text-[10px] uppercase text-white/40">
          {t.lyricsSourceGroupAvailable}
        </div>
      )}

      {sources?.map((source, index) => (
        <button
          // +1 چون آیتمِ «خودکار» جای صفر را گرفته
          ref={(el) => {
            itemRefs.current[index + 1] = el
          }}
          key={source.id}
          role="menuitemradio"
          aria-checked={current === source.id}
          aria-disabled={false}
          title={source.terms_note ?? undefined}
          onClick={() => {
            onSelect(source.id)
            setOpen(false)
          }}
          className="flex w-full items-center justify-between gap-2 rounded-xl px-3 py-2 text-start text-sm text-white/90 hover:bg-white/10 focus:bg-white/10 focus:outline-none cursor-pointer"
        >
          <span className="flex items-center gap-1.5 min-w-0">
            <span className="truncate">{source.label}</span>
            {capabilityTags(source).map((tag) => (
              <span key={tag} className="shrink-0 rounded bg-white/10 px-1 text-[9px] text-white/60">
                {tag}
              </span>
            ))}
            {source.experimental && (
              <span className="shrink-0 rounded bg-amber-500/20 px-1 text-[9px] text-amber-300">
                {t.lyricsSourceExperimental}
              </span>
            )}
            {source.terms_note && (
              <span aria-hidden className="shrink-0 text-[9px] text-sky-300/70">
                ⓘ
              </span>
            )}
          </span>
          <span className="shrink-0 text-[10px] text-white/50">{statusText(t, source, current)}</span>
        </button>
      ))}

      {onRetry && (
        <button
          onClick={() => {
            onRetry()
            setOpen(false)
          }}
          className="w-full rounded-xl px-3 py-2 text-start text-xs text-white/70 hover:bg-white/10 focus:bg-white/10 focus:outline-none cursor-pointer"
        >
          {t.lyricsSourceRetry}
        </button>
      )}

      {unavailable.length > 0 && (
        <div className="border-t border-white/10 pt-1">
          <button
            onClick={() => setShowUnusable((v) => !v)}
            aria-expanded={showUnusable}
            className="flex w-full items-center justify-between px-3 py-1.5 text-[10px] uppercase text-white/40 hover:text-white/60 cursor-pointer"
          >
            <span>{t.lyricsSourceUnusable}</span>
            <span aria-hidden>{showUnusable ? '−' : '+'}</span>
          </button>
          {showUnusable &&
            unavailable.map((source) => (
              <div
                key={source.id}
                aria-disabled="true"
                title={source.unavailable_reason ?? undefined}
                className="flex items-center justify-between gap-2 px-3 py-1.5 text-xs text-white/35"
              >
                <span className="truncate">{source.label}</span>
                <span className="shrink-0 text-[10px]">
                  {source.status === 'blocked'
                    ? t.srcBlocked
                    : source.status === 'needs_setup'
                      ? t.srcNeedsSetup
                      : t.srcDisabled}
                </span>
              </div>
            ))}
        </div>
      )}
    </>
  )

  const menu = (
    <div
      ref={menuRef}
      role="menu"
      aria-label={t.lyricsSource}
      onKeyDown={onMenuKeyDown}
      style={itemStyle}
      className={
        sheet
          ? 'fixed inset-x-0 bottom-0 z-[70] max-h-[75vh] overflow-y-auto rounded-t-2xl bg-black/95 p-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] shadow-2xl backdrop-blur-xl border-t border-white/15 space-y-1'
          : 'z-[70] w-72 overflow-y-auto rounded-2xl bg-black/90 p-2 pb-[calc(0.5rem+env(safe-area-inset-bottom))] shadow-2xl backdrop-blur-xl border border-white/15 space-y-1'
      }
    >
      {sheet && (
        <button
          onClick={() => setOpen(false)}
          className="mb-1 w-full rounded-xl px-3 py-2 text-center text-xs text-white/60 hover:bg-white/10 cursor-pointer"
        >
          {t.lyricsSourceClose}
        </button>
      )}
      {list}
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
        <span className="truncate max-w-40">{triggerText}</span>
      </button>
      {open && typeof document !== 'undefined' && createPortal(menu, document.body)}
    </>
  )
}
