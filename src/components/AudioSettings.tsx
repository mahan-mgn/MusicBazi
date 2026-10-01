import { useEffect, useState } from 'react'
import { usePopover } from '../lib/usePopover'
import { EQ_PRESETS, engine, MAX_BOOST_DB, type EqPreset } from '../lib/audioEngine'
import { digits } from '../lib/format'
import { useI18n } from '../lib/i18n'
import { usePlayer } from '../store/player'
import { MAX_CROSSFADE, useSettings } from '../store/settings'
import Range from './Range'
import { SlidersIcon, TimerIcon } from './icons'

const SLEEP_CHOICES = [15, 30, 45, 60]

/** «۱۲:۳۴» مانده تا خاموشی */
function remaining(at: number): string {
  const seconds = Math.max(0, Math.round((at - Date.now()) / 1000))
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

/**
 * تنظیم‌های صدا: هم‌ترازی بلندی، کراس‌فید، اکولایزر و تایمر خواب.
 *
 * همه‌جا از یک پاپ‌آور می‌آیند چون هر چهارتا «چطور شنیده شود»اند، نه «چه چیزی
 * پخش شود» — و هیچ‌کدام آن‌قدر پرکاربرد نیستند که جایی روی نوار پخش بگیرند.
 */
export default function AudioSettings() {
  const { t, lang } = useI18n()
  const { normalize, crossfade, eq, boost, setNormalize, setCrossfade, setEq, setBoost } =
    useSettings()
  const sleepAt = usePlayer((s) => s.sleepAt)
  const setSleepTimer = usePlayer((s) => s.setSleepTimer)
  const [open, setOpen] = useState(false)
  const [, tick] = useState(0)
  const box = usePopover<HTMLDivElement>(open, () => setOpen(false))

  // شمارشِ معکوسِ تایمر باید زنده باشد، ولی فقط وقتی دیده می‌شود
  useEffect(() => {
    if (!open || typeof sleepAt !== 'number') return
    const id = setInterval(() => tick((n) => n + 1), 1000)
    return () => clearInterval(id)
  }, [open, sleepAt])

  const eqLabel: Record<EqPreset, string> = {
    off: t.eqOff,
    bass: t.eqBass,
    vocal: t.eqVocal,
    treble: t.eqTreble,
    loud: t.eqLoud,
  }

  // موتور فقط وقتی گراف دارد که مرورگر Web Audio بدهد؛ بدونش این سه تنظیم
  // کاری نمی‌کنند و بهتر است صریح گفته شود تا کاربر فکر نکند خراب است.
  // قبل از اولین پخش هنوز هیچ دکی ساخته نشده و «ندارد» جوابِ درستی نیست.
  const unsupported = engine.hasSource() && !engine.graphReady()

  return (
    <div ref={box} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={t.audioSettings}
        title={t.audioSettings}
        className={`grid size-7 place-items-center rounded-md transition hover:text-fg ${
          sleepAt !== null || crossfade > 0 || eq !== 'off' || boost > 0
            ? 'text-accent'
            : 'text-muted-2'
        }`}
      >
        <SlidersIcon className="size-4" />
      </button>

      {open && (
        <div
          role="dialog"
          aria-label={t.audioSettings}
          className="absolute bottom-full end-0 z-40 mb-2 w-[min(18rem,calc(100vw-2.5rem))] space-y-3 rounded-xl border border-line bg-panel p-3 shadow-xl"
        >
          <label className="flex cursor-pointer items-start gap-2">
            <input
              type="checkbox"
              checked={normalize}
              onChange={(e) => setNormalize(e.target.checked)}
              className="mt-0.5 size-3.5 shrink-0 accent-[var(--accent)]"
            />
            <span className="min-w-0">
              <span className="block text-xs font-medium">{t.normalize}</span>
              <span className="block text-[11px] leading-snug text-muted-2">{t.normalizeHint}</span>
            </span>
          </label>

          <div>
            <div className="mb-1 flex items-center justify-between">
              <span className="text-xs font-medium">{t.boost}</span>
              <span className="text-[11px] text-muted-2">
                {boost === 0 ? t.boostOff : t.boostValue(boost)}
              </span>
            </div>
            <div dir="ltr">
              <Range value={boost} max={MAX_BOOST_DB} onChange={setBoost} label={t.boost} />
            </div>
            <p className="mt-1 text-[11px] leading-snug text-muted-2">{t.boostHint}</p>
          </div>

          <div>
            <div className="mb-1 flex items-center justify-between">
              <span className="text-xs font-medium">{t.crossfade}</span>
              <span className="text-[11px] text-muted-2">
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

          <div>
            <span className="mb-1 block text-xs font-medium">{t.equalizer}</span>
            <div className="flex flex-wrap gap-1">
              {(Object.keys(EQ_PRESETS) as EqPreset[]).map((preset) => (
                <button
                  key={preset}
                  onClick={() => setEq(preset)}
                  aria-pressed={eq === preset}
                  className={`rounded-full border px-2.5 py-1 text-[11px] transition ${
                    eq === preset
                      ? 'border-accent bg-accent font-semibold text-accent-fg'
                      : 'border-line text-muted hover:text-fg'
                  }`}
                >
                  {eqLabel[preset]}
                </button>
              ))}
            </div>
          </div>

          <div className="border-t border-line-soft pt-3">
            <div className="mb-1 flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-xs font-medium">
                <TimerIcon className="size-3.5 text-muted-2" />
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
                className={`rounded-full border px-2.5 py-1 text-[11px] transition ${
                  sleepAt === null
                    ? 'border-accent bg-accent font-semibold text-accent-fg'
                    : 'border-line text-muted hover:text-fg'
                }`}
              >
                {t.sleepOff}
              </button>
              <button
                onClick={() => setSleepTimer(sleepAt === 'track_end' ? null : 'track_end')}
                aria-pressed={sleepAt === 'track_end'}
                className={`rounded-full border px-2.5 py-1 text-[11px] transition ${
                  sleepAt === 'track_end'
                    ? 'border-accent bg-accent font-semibold text-accent-fg'
                    : 'border-line text-muted hover:text-fg'
                }`}
              >
                {t.sleepEndOfTrack}
              </button>
              {SLEEP_CHOICES.map((minutes) => (
                <button
                  key={minutes}
                  onClick={() => setSleepTimer(minutes)}
                  className="rounded-full border border-line px-2.5 py-1 text-[11px] text-muted transition hover:text-fg"
                >
                  {t.sleepMinutes(minutes)}
                </button>
              ))}
            </div>
          </div>

          {unsupported && (
            <p className="border-t border-line-soft pt-2 text-[11px] text-muted-2">
              {t.audioGraphMissing}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
