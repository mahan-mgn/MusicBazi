import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { engine, MAX_BOOST_DB } from '../lib/audioEngine'
import { MANUAL_BANDS_HZ, MANUAL_RANGE_DB } from '../lib/audio/dsp/EqCurve'
import { EQ_PRESET_ORDER, EQ_PRESETS_DB, matchingPreset, type EqPresetName } from '../lib/audio/dsp/EqPresets'
import { digits } from '../lib/format'
import { useI18n } from '../lib/i18n'
import { isSheetLayout } from '../lib/popoverPlacement'
import { useBackDismiss } from '../lib/back'
import { useArtworkTheme } from '../lib/useArtworkTheme'
import { pageThemeVars } from '../lib/pageTheme'
import { usePlayer } from '../store/player'
import { MAX_CROSSFADE, useSettings } from '../store/settings'
import Range from './Range'
import AudioPipelineModal from './AudioPipelineModal'
import { CloseIcon, SlidersIcon, TimerIcon } from './icons'

const SLEEP_CHOICES = [15, 30, 45, 60]

/** «۱۲:۳۴» مانده تا خاموشی */
function remaining(at: number): string {
  const seconds = Math.max(0, Math.round((at - Date.now()) / 1000))
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

interface Props {
  /** نمایش به عنوان ردیف کامل منو (برای منوی سه‌نقطه در NowPlaying) */
  asMenuItem?: boolean
  className?: string
  /** کنترل وضعیت باز/بسته از والد */
  open?: boolean
  onClose?: () => void
  /** مرجع المانِ لنگر جهت موقعیت‌یابی پاپ‌اور در حالت کنترل‌شده */
  anchorRef?: React.RefObject<HTMLElement | null>
}

/**
 * تنظیم‌های صدا: هم‌ترازی بلندی، کراس‌فید، اکولایزر و تایمر خواب.
 *
 * تم و رنگِ پس‌زمینه را مستقیماً از کاورِ آهنگ جاری می‌گیرد تا کاملاً با صفحهٔ
 * Now Playing و نوار پخش هم‌رنگ و هماهنگ باشد.
 *
 * با استفاده از Portal به document.body متصل می‌شود تا هرگز توسط کادرهای والد با
 * backdrop-filter، overflow-hidden یا transform دچار به هم ریختگی موقعیت نشود.
 * موقعیت آن هوشمندانه در ویوپورت کلمپ می‌شود تا هرگز از سقف یا کف پنجره بیرون نزند.
 */

/**
 * پد تون دوبعدی — معادل TonePad اندروید: محور افقی tilt (بم↔زیر) و محور
 * عمودی contour میانی، هر کدام ۵± گام (هر گام ۱٫۲ دسی‌بل). درگ با pointer —
 * هم موس هم لمس. جهت همیشه ltr است تا محورها در RTL برعکس نشوند.
 */
function TonePad({
  x,
  y,
  disabled,
  label,
  onChange,
}: {
  x: number
  y: number
  disabled: boolean
  label: string
  onChange: (v: { x: number; y: number }) => void
}) {
  const padRef = useRef<HTMLDivElement>(null)
  const dragging = useRef(false)

  const apply = useCallback(
    (clientX: number, clientY: number) => {
      const rect = padRef.current?.getBoundingClientRect()
      if (!rect || rect.width === 0) return
      const nx = ((clientX - rect.left) / rect.width) * 2 - 1
      const ny = 1 - ((clientY - rect.top) / rect.height) * 2
      onChange({ x: Math.round(nx * 5), y: Math.round(ny * 5) })
    },
    [onChange],
  )

  return (
    <div
      ref={padRef}
      dir="ltr"
      role="slider"
      aria-label={label}
      aria-valuemin={-5}
      aria-valuemax={5}
      aria-valuenow={x}
      aria-valuetext={`tilt ${x}, contour ${y}`}
      aria-disabled={disabled}
      onPointerDown={(e) => {
        if (disabled) return
        dragging.current = true
        e.currentTarget.setPointerCapture(e.pointerId)
        apply(e.clientX, e.clientY)
      }}
      onPointerMove={(e) => {
        if (!dragging.current || disabled) return
        apply(e.clientX, e.clientY)
      }}
      onPointerUp={() => {
        dragging.current = false
      }}
      className={`relative mt-2 h-24 w-full cursor-pointer touch-none rounded-lg border border-white/15 bg-white/5 ${
        disabled ? 'opacity-40' : ''
      }`}
    >
      {/* محورهای میانی */}
      <div className="pointer-events-none absolute inset-x-0 top-1/2 h-px bg-white/10" />
      <div className="pointer-events-none absolute inset-y-0 left-1/2 w-px bg-white/10" />
      {/* نشانگر */}
      <div
        className="pointer-events-none absolute size-4 -translate-x-1/2 -translate-y-1/2 rounded-full bg-accent shadow"
        style={{
          left: `${((x + 5) / 10) * 100}%`,
          top: `${(1 - (y + 5) / 10) * 100}%`,
        }}
      />
    </div>
  )
}

export default function AudioSettings({
  asMenuItem = false,
  className = '',
  open: propsOpen,
  onClose,
  anchorRef,
}: Props) {
  const { t, lang } = useI18n()
  const {
    normalize,
    crossfade,
    automix,
    smartDj,
    eqBands,
    tone,
    balance,
    eqEnabled,
    boost,
    setNormalize,
    setCrossfade,
    setAutomix,
    setSmartDj,
    setEqBands,
    setTone,
    setBalance,
    setEqEnabled,
    setBoost,
  } = useSettings()
  const sleepAt = usePlayer((s) => s.sleepAt)
  const setSleepTimer = usePlayer((s) => s.setSleepTimer)
  const currentItem = usePlayer((s) => s.queue[s.index])

  // هماهنگی تم با پس‌زمینه رنگی کاور آهنگ جاری
  const theme = useArtworkTheme(
    currentItem?.track.artworkUrl ?? null,
    currentItem?.track.albumId ?? currentItem?.track.id ?? 'audio-settings',
  )
  const tintStyle = useMemo(() => pageThemeVars(theme), [theme])

  const isControlled = typeof propsOpen === 'boolean'
  const [internalOpen, setInternalOpen] = useState(false)
  const open = isControlled ? propsOpen : internalOpen

  const setOpen = useCallback(
    (next: boolean | ((prev: boolean) => boolean)) => {
      const val = typeof next === 'function' ? next(open) : next
      if (!val) onClose?.()
      if (!isControlled) setInternalOpen(val)
    },
    [isControlled, onClose, open],
  )

  const [sheet, setSheet] = useState(false)
  const [showPipeline, setShowPipeline] = useState(false)
  const [, tick] = useState(0)

  const triggerRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const [panelStyle, setPanelStyle] = useState<CSSProperties>({ visibility: 'hidden' })

  useBackDismiss(open, () => setOpen(false))

  const getAnchor = useCallback(() => {
    return anchorRef?.current ?? triggerRef.current
  }, [anchorRef])

  // بستن با کلیکِ بیرون
  useEffect(() => {
    if (!open) return
    const onDown = (e: PointerEvent) => {
      const target = e.target as Node
      const anchor = getAnchor()
      if (anchor?.contains(target) || panelRef.current?.contains(target)) return
      setOpen(false)
    }
    document.addEventListener('pointerdown', onDown)
    return () => document.removeEventListener('pointerdown', onDown)
  }, [open, getAnchor, setOpen])

  // بستن با کلید Escape
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false)
        getAnchor()?.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, getAnchor, setOpen])

  // محاسبه موقعیت هوشمند پاپ‌اور با تضمین عدم خروج از سقف، کف و کناره‌های پنجره
  const reposition = useCallback(() => {
    const trigger = getAnchor()
    const panel = panelRef.current
    if (!trigger || !panel) return

    const isSheet = isSheetLayout(window.innerWidth)
    setSheet(isSheet)
    if (isSheet) {
      setPanelStyle({ visibility: 'visible' })
      return
    }

    const a = trigger.getBoundingClientRect()
    const viewportHeight = window.innerHeight
    const viewportWidth = window.innerWidth
    const margin = 12
    const gap = 8

    // عرض پاپ‌اور (حداکثر ۱۸ رِم یا عرض ویوپورت منهای حاشیه‌ها)
    const panelWidth = Math.min(292, viewportWidth - 2 * margin)
    const panelHeight = panel.scrollHeight || 480

    const spaceAbove = a.top - margin - gap
    const spaceBelow = viewportHeight - a.bottom - margin - gap

    // تصمیم‌گیری درباره باز شدن رو به بالا یا رو به پایین
    const placement = spaceAbove >= panelHeight || spaceAbove >= spaceBelow ? 'top' : 'bottom'
    const available = placement === 'top' ? spaceAbove : spaceBelow
    const maxHeight = Math.max(200, Math.min(panelHeight, available, viewportHeight - 2 * margin))

    const top = placement === 'top' ? a.top - gap - maxHeight : a.bottom + gap
    const clampedTop = Math.max(margin, Math.min(top, viewportHeight - maxHeight - margin))

    // تنظیم افقی بر اساس جهت زبان بدون خروج از لبه‌های راست و چپ
    let left: number
    if (lang === 'fa') {
      left = Math.max(margin, Math.min(a.left, viewportWidth - panelWidth - margin))
    } else {
      const desiredLeft = a.right - panelWidth
      left = Math.max(margin, Math.min(desiredLeft, viewportWidth - panelWidth - margin))
    }

    setPanelStyle({
      position: 'fixed',
      top: `${Math.round(clampedTop)}px`,
      left: `${Math.round(left)}px`,
      width: `${Math.round(panelWidth)}px`,
      maxHeight: `${Math.round(maxHeight)}px`,
      visibility: 'visible',
    })
  }, [lang])

  useLayoutEffect(() => {
    if (!open) return
    reposition()
    window.addEventListener('resize', reposition)
    window.addEventListener('scroll', reposition, true)
    return () => {
      window.removeEventListener('resize', reposition)
      window.removeEventListener('scroll', reposition, true)
    }
  }, [open, reposition])

  // شمارشِ معکوسِ تایمر باید زنده باشد، ولی فقط وقتی دیده می‌شود
  useEffect(() => {
    if (!open || typeof sleepAt !== 'number') return
    const id = setInterval(() => tick((n) => n + 1), 1000)
    return () => clearInterval(id)
  }, [open, sleepAt])

  const eqPresetLabels: Record<EqPresetName, string> = {
    FLAT: t.eqPresetFlat,
    ACOUSTIC: t.eqPresetAcoustic,
    BASS_BOOST: t.eqPresetBassBoost,
    BASS_CUT: t.eqPresetBassCut,
    VOCAL: t.eqPresetVocal,
    TREBLE_BOOST: t.eqPresetTrebleBoost,
    TREBLE_CUT: t.eqPresetTrebleCut,
    LOUDNESS: t.eqPresetLoudness,
    SPOKEN_WORD: t.eqPresetSpokenWord,
    ELECTRONIC: t.eqPresetElectronic,
    ROCK: t.eqPresetRock,
    HIP_HOP: t.eqPresetHipHop,
    JAZZ: t.eqPresetJazz,
    CLASSICAL: t.eqPresetClassical,
    SMALL_SPEAKERS: t.eqPresetSmallSpeakers,
    LATE_NIGHT: t.eqPresetLateNight,
    CUSTOM: t.eqCustom,
  }

  const bandLabel = (hz: number): string =>
    hz >= 1000 ? `${digits(hz / 1000, lang)}k` : `${digits(hz, lang)}`

  const unsupported = engine.hasSource() && !engine.graphReady()

  const content = (
    <>
      <div className="rounded-xl bg-white/5 border border-white/10 p-2.5 transition">
        <div className="flex items-center justify-between gap-2 mb-1">
          <span className="text-xs font-bold text-white flex items-center gap-1.5">
            {t.normalize}
            <span
              className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full ${
                normalize ? 'bg-accent/25 text-accent font-bold' : 'bg-white/10 text-white/50'
              }`}
            >
              {normalize ? t.normalizeActive : t.normalizeInactive}
            </span>
          </span>
          <button
            type="button"
            role="switch"
            dir="ltr"
            aria-checked={normalize}
            onClick={() => setNormalize(!normalize)}
            aria-label={t.normalize}
            className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
              normalize ? 'bg-accent' : 'bg-white/20'
            }`}
          >
            <span
              aria-hidden="true"
              className={`pointer-events-none inline-block size-4 transform rounded-full bg-white shadow-md ring-0 transition duration-200 ease-in-out ${
                normalize ? 'translate-x-4' : 'translate-x-0'
              }`}
            />
          </button>
        </div>
        <p className="text-[11px] leading-snug text-white/60">{t.normalizeHint}</p>
      </div>

      <div>
        <div className="mb-1 flex items-center justify-between">
          <span className="text-xs font-medium text-white">{t.boost}</span>
          <span className="text-[11px] text-white/60">
            {boost === 0 ? t.boostOff : t.boostValue(boost)}
          </span>
        </div>
        <div dir="ltr">
          <Range value={boost} max={MAX_BOOST_DB} onChange={setBoost} label={t.boost} />
        </div>
        <p className="mt-1 text-[11px] leading-snug text-white/60">{t.boostHint}</p>
      </div>

      <div>
        <div className="mb-1 flex items-center justify-between">
          <span className="text-xs font-medium text-white">{t.crossfade}</span>
          <span className="text-[11px] text-white/60">
            {crossfade === 0 ? t.crossfadeOff : t.crossfadeValue(crossfade)}
          </span>
        </div>
        <div dir="ltr">
          <Range
            value={crossfade}
            max={MAX_CROSSFADE}
            onChange={setCrossfade}
            label={t.crossfade}
          />
        </div>
      </div>

      {crossfade > 0 && (
        <>
          <div className="rounded-xl bg-white/5 border border-white/10 p-2.5 transition">
            <div className="flex items-center justify-between gap-2 mb-1">
              <span className="text-xs font-bold text-white flex items-center gap-1.5">
                {t.automix}
                <span
                  className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full ${
                    automix ? 'bg-accent/25 text-accent font-bold' : 'bg-white/10 text-white/50'
                  }`}
                >
                  {automix ? t.automixActive : t.automixInactive}
                </span>
              </span>
              <button
                type="button"
                role="switch"
                dir="ltr"
                aria-checked={automix}
                onClick={() => setAutomix(!automix)}
                aria-label={t.automix}
                className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
                  automix ? 'bg-accent' : 'bg-white/20'
                }`}
              >
                <span
                  aria-hidden="true"
                  className={`pointer-events-none inline-block size-4 transform rounded-full bg-white shadow-md ring-0 transition duration-200 ease-in-out ${
                    automix ? 'translate-x-4' : 'translate-x-0'
                  }`}
                />
              </button>
            </div>
            <p className="text-[11px] leading-snug text-white/60">{t.automixHint}</p>
          </div>

          <div className="rounded-xl bg-white/5 border border-white/10 p-2.5 transition">
            <div className="flex items-center justify-between gap-2 mb-1">
              <span className="text-xs font-bold text-white flex items-center gap-1.5">
                {t.smartDj}
                <span
                  className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full ${
                    smartDj ? 'bg-accent/25 text-accent font-bold' : 'bg-white/10 text-white/50'
                  }`}
                >
                  {smartDj ? t.smartDjActive : t.smartDjInactive}
                </span>
              </span>
              <button
                type="button"
                role="switch"
                dir="ltr"
                aria-checked={smartDj}
                onClick={() => setSmartDj(!smartDj)}
                aria-label={t.smartDj}
                className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
                  smartDj ? 'bg-accent' : 'bg-white/20'
                }`}
              >
                <span
                  aria-hidden="true"
                  className={`pointer-events-none inline-block size-4 transform rounded-full bg-white shadow-md ring-0 transition duration-200 ease-in-out ${
                    smartDj ? 'translate-x-4' : 'translate-x-0'
                  }`}
                />
              </button>
            </div>
            <p className="text-[11px] leading-snug text-white/60">{t.smartDjHint}</p>
          </div>
        </>
      )}

      <div className="rounded-xl bg-white/5 border border-white/10 p-2.5 transition">
        <div className="flex items-center justify-between gap-2 mb-2">
          <span className="text-xs font-bold text-white flex items-center gap-1.5">
            {t.equalizer}
            <span
              className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full ${
                eqEnabled ? 'bg-accent/25 text-accent font-bold' : 'bg-white/10 text-white/50'
              }`}
            >
              {eqEnabled ? t.equalizerActive : t.equalizerInactive}
            </span>
          </span>
          <button
            type="button"
            role="switch"
            dir="ltr"
            aria-checked={eqEnabled}
            onClick={() => setEqEnabled(!eqEnabled)}
            aria-label={t.equalizer}
            className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
              eqEnabled ? 'bg-accent' : 'bg-white/20'
            }`}
          >
            <span
              aria-hidden="true"
              className={`pointer-events-none inline-block size-4 transform rounded-full bg-white shadow-md ring-0 transition duration-200 ease-in-out ${
                eqEnabled ? 'translate-x-4' : 'translate-x-0'
              }`}
            />
          </button>
        </div>
        <div className={`flex flex-wrap gap-1 transition-opacity duration-200 ${eqEnabled ? 'opacity-100' : 'opacity-40'}`}>
          {EQ_PRESET_ORDER.filter((preset) => preset !== 'CUSTOM').map((preset) => (
            <button
              key={preset}
              onClick={() => {
                const bands = EQ_PRESETS_DB[preset]
                if (bands) setEqBands([...bands])
                if (!eqEnabled) setEqEnabled(true)
              }}
              aria-pressed={eqEnabled && matchingPreset(eqBands) === preset}
              className={`rounded-full border px-2.5 py-1 text-[11px] transition cursor-pointer ${
                eqEnabled && matchingPreset(eqBands) === preset
                  ? 'border-accent bg-accent font-semibold text-accent-fg'
                  : 'border-white/15 text-white/70 hover:bg-white/10 hover:text-white'
              }`}
            >
              {eqPresetLabels[preset]}
            </button>
          ))}
        </div>

        {/* هفت باند دستی — همان چیدمان اپ اندروید */}
        <div className={`mt-2.5 space-y-1.5 transition-opacity duration-200 ${eqEnabled ? 'opacity-100' : 'opacity-40'}`}>
          <div className="flex items-center justify-between">
            <span className="text-[11px] text-white/70">{t.eqManual}</span>
            <button
              type="button"
              onClick={() => setEqBands([0, 0, 0, 0, 0, 0, 0])}
              disabled={!eqEnabled}
              className="text-[10px] text-white/50 hover:text-white transition cursor-pointer disabled:cursor-default disabled:opacity-0"
            >
              {t.eqReset}
            </button>
          </div>
          {MANUAL_BANDS_HZ.map((hz, i) => (
            <div key={hz} className="flex items-center gap-2">
              <span dir="ltr" className="w-9 shrink-0 text-[10px] text-white/50 tabular-nums">
                {bandLabel(hz)}
              </span>
              <div dir="ltr" className="flex-1">
                <input
                  type="range"
                  min={-MANUAL_RANGE_DB}
                  max={MANUAL_RANGE_DB}
                  step={0.5}
                  value={eqBands[i] ?? 0}
                  disabled={!eqEnabled}
                  onChange={(e) => {
                    const next = [...eqBands]
                    next[i] = Number(e.target.value)
                    setEqBands(next)
                  }}
                  aria-label={`${t.eqManual} ${bandLabel(hz)}`}
                  className="seek w-full"
                  style={{ '--pct': `${(((eqBands[i] ?? 0) + MANUAL_RANGE_DB) / (MANUAL_RANGE_DB * 2)) * 100}%` } as CSSProperties}
                />
              </div>
              <span dir="ltr" className="w-10 shrink-0 text-left text-[10px] text-white/50 tabular-nums">
                {digits(eqBands[i] ?? 0, lang)}dB
              </span>
            </div>
          ))}

          {/* پد تون: افقی tilt، عمودی contour */}
          <TonePad
            x={tone.x}
            y={tone.y}
            disabled={!eqEnabled}
            label={t.eqTonePad}
            onChange={({ x, y }) => setTone({ x, y })}
          />
          <p className="text-[10px] leading-snug text-white/50">{t.eqToneHint}</p>

          {/* بالانس چپ/راست */}
          <div className="flex items-center gap-2 pt-1">
            <span className="text-[10px] text-white/50">{t.eqBalanceLeft}</span>
            <div dir="ltr" className="flex-1">
              <input
                type="range"
                min={-1}
                max={1}
                step={0.1}
                value={balance}
                disabled={!eqEnabled}
                onChange={(e) => setBalance(Number(e.target.value))}
                aria-label={t.eqBalance}
                className="seek w-full"
                style={{ '--pct': `${((balance + 1) / 2) * 100}%` } as CSSProperties}
              />
            </div>
            <span className="text-[10px] text-white/50">{t.eqBalanceRight}</span>
          </div>
        </div>
      </div>

      <div className="border-t border-white/10 pt-3">
        <div className="mb-1 flex items-center justify-between">
          <span className="flex items-center gap-1.5 text-xs font-medium text-white">
            <TimerIcon className="size-3.5 text-white/60" />
            {t.sleepTimer}
          </span>
          {sleepAt !== null && (
            <span className="text-[11px] text-accent">
              {sleepAt === 'track_end'
                ? t.sleepEndOfTrack
                : t.sleepIn(digits(remaining(sleepAt), lang))}
            </span>
          )}
        </div>
        <div className="flex flex-wrap gap-1">
          <button
            onClick={() => setSleepTimer(null)}
            aria-pressed={sleepAt === null}
            className={`rounded-full border px-2.5 py-1 text-[11px] transition cursor-pointer ${
              sleepAt === null
                ? 'border-accent bg-accent font-semibold text-accent-fg'
                : 'border-white/15 text-white/70 hover:bg-white/10 hover:text-white'
            }`}
          >
            {t.sleepOff}
          </button>
          <button
            onClick={() => setSleepTimer(sleepAt === 'track_end' ? null : 'track_end')}
            aria-pressed={sleepAt === 'track_end'}
            className={`rounded-full border px-2.5 py-1 text-[11px] transition cursor-pointer ${
              sleepAt === 'track_end'
                ? 'border-accent bg-accent font-semibold text-accent-fg'
                : 'border-white/15 text-white/70 hover:bg-white/10 hover:text-white'
            }`}
          >
            {t.sleepEndOfTrack}
          </button>
          {SLEEP_CHOICES.map((minutes) => (
            <button
              key={minutes}
              onClick={() => setSleepTimer(minutes)}
              className="rounded-full border border-white/15 px-2.5 py-1 text-[11px] text-white/70 transition hover:bg-white/10 hover:text-white cursor-pointer"
            >
              {t.sleepMinutes(minutes)}
            </button>
          ))}
        </div>
      </div>

      <div className="border-t border-white/10 pt-2">
        <button
          onClick={() => {
            setOpen(false)
            setShowPipeline(true)
          }}
          className="w-full flex items-center justify-between rounded-lg border border-white/15 bg-white/5 px-2.5 py-1.5 text-xs font-medium text-white/80 hover:bg-white/10 hover:text-white transition cursor-pointer"
        >
          <span>{lang === 'fa' ? 'مسیر صوتی و دیاگنوستیک' : 'Audio Pipeline'}</span>
          <span className="text-[11px] text-accent">➔</span>
        </button>
      </div>

      {unsupported && (
        <p className="border-t border-white/10 pt-2 text-[11px] text-white/50">
          {t.audioGraphMissing}
        </p>
      )}
    </>
  )

  const trigger = isControlled ? null : asMenuItem ? (
    <button
      ref={triggerRef}
      onClick={() => setOpen((v) => !v)}
      aria-haspopup="dialog"
      aria-expanded={open}
      className={`flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-xs font-semibold text-white/90 hover:bg-white/15 transition cursor-pointer ${className}`}
    >
      <SlidersIcon className="size-4 text-white/70" />
      <span>{t.audioSettings}</span>
    </button>
  ) : (
    <button
      ref={triggerRef}
      onClick={() => setOpen((v) => !v)}
      aria-haspopup="dialog"
      aria-expanded={open}
      aria-label={t.audioSettings}
      title={t.audioSettings}
      className={`grid size-7 place-items-center rounded-md transition hover:text-fg cursor-pointer ${
        sleepAt !== null ||
        crossfade > 0 ||
        (eqEnabled && matchingPreset(eqBands) !== 'FLAT') ||
        boost > 0
          ? 'text-accent'
          : 'text-muted-2'
      } ${className}`}
    >
      <SlidersIcon className="size-4" />
    </button>
  )

  const dynamicBackgroundStyle: CSSProperties = {
    ...tintStyle,
    backgroundColor: 'var(--page-bg, #0a0a0c)',
    backgroundImage:
      'radial-gradient(circle at 50% 0%, var(--page-tint-surface, rgba(255,255,255,0.08)) 0%, transparent 80%), linear-gradient(180deg, var(--page-bg, #0a0a0c) 0%, var(--page-base, #060608) 100%)',
  }

  const modalNode = (
    <>
      {sheet ? (
        <div className="fixed inset-0 z-[80] flex flex-col justify-end bg-black/60 backdrop-blur-sm animate-fade-in">
          <div className="fixed inset-0" onClick={() => setOpen(false)} />
          <div
            ref={panelRef}
            role="dialog"
            aria-label={t.audioSettings}
            style={dynamicBackgroundStyle}
            className="relative z-10 max-h-[85vh] w-full rounded-t-3xl border-t border-white/15 p-4 pb-[calc(1.5rem+env(safe-area-inset-bottom))] shadow-2xl space-y-3.5 overflow-y-auto text-white"
          >
            <div className="mx-auto -mt-1 mb-2 h-1 w-10 rounded-full bg-white/20" />
            <div className="flex items-center justify-between pb-1 border-b border-white/15">
              <h3 className="text-sm font-bold text-white flex items-center gap-2">
                <SlidersIcon className="size-4 text-accent" />
                {t.audioSettings}
              </h3>
              <button
                onClick={() => setOpen(false)}
                aria-label={t.close}
                className="rounded-full p-1 text-white/60 hover:text-white cursor-pointer"
              >
                <CloseIcon className="size-5" />
              </button>
            </div>
            {content}
          </div>
        </div>
      ) : (
        <div
          ref={panelRef}
          role="dialog"
          aria-label={t.audioSettings}
          style={{
            ...panelStyle,
            ...dynamicBackgroundStyle,
          }}
          className="z-[80] space-y-3 rounded-2xl border border-white/15 p-3.5 shadow-2xl backdrop-blur-2xl text-white overflow-y-auto scrollbar-thin"
        >
          <div className="flex items-center justify-between pb-1 border-b border-white/15">
            <h3 className="text-xs font-bold text-white flex items-center gap-1.5">
              <SlidersIcon className="size-3.5 text-accent" />
              {t.audioSettings}
            </h3>
            <button
              onClick={() => setOpen(false)}
              aria-label={t.close}
              className="rounded-full p-0.5 text-white/60 hover:text-white cursor-pointer"
            >
              <CloseIcon className="size-4" />
            </button>
          </div>
          {content}
        </div>
      )}
    </>
  )

  return (
    <>
      {trigger}
      {open && typeof document !== 'undefined' && createPortal(modalNode, document.body)}
      <AudioPipelineModal open={showPipeline} onClose={() => setShowPipeline(false)} />
    </>
  )
}
