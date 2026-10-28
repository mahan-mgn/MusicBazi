import { create } from 'zustand'
import { engine, MAX_BOOST_DB } from '../lib/audioEngine'
import { matchingPreset, type EqPresetName } from '../lib/audio/dsp/EqPresets'
import { MANUAL_RANGE_DB } from '../lib/audio/dsp/EqCurve'
import { setReducedMotionOverride } from '../lib/motion'
import { nativeSetCrossfade, nativeSetEqualizer, nativeSetSpatialAudio, syncStatusBar } from '../lib/native'
import { setErrorReportingEnabled } from '../lib/telemetry'
import { readStored, readStoredAs, readStoredNumber, removeStored, writeStored } from '../lib/storage'
import type { Quality } from '../lib/types'

/**
 * سه حالتِ تم، نه دو تا.
 *
 * «خودکار» یعنی از سیستم‌عامل پیروی کن. تمِ روشنِ تحمیلی روی گوشی‌ای که کاربر
 * عمداً در حالتِ شب گذاشته، دقیقاً همان آزارِ معکوس را می‌دهد.
 */
type Theme = 'dark' | 'light' | 'system'
/** همان تم، بعد از حل‌شدنِ `system` — چیزی که واقعاً اعمال می‌شود */
type ResolvedTheme = 'dark' | 'light'
export type NativeAudioEngineMode = 'auto' | 'on' | 'off'

/** بیشترین کراس‌فیدِ مجاز (ثانیه) — بالاتر از این، دو ترک روی هم می‌مانند نه محو */
export const MAX_CROSSFADE = 12

/** سقفِ دانلودِ هم‌زمان — کمینه/بیشینه */
export const MIN_CONCURRENT_DOWNLOADS = 1
export const MAX_CONCURRENT_DOWNLOADS = 8

export { MANUAL_RANGE_DB, matchingPreset }
export type { EqPresetName }

interface SettingsState {
  quality: Quality
  theme: Theme
  /** فعال‌بودنِ شیشه مایع (Liquid Glass) مطابق با BitChord */
  liquidGlass: boolean
  /** کم‌کردنِ انیمیشن‌ها، مستقل از تنظیمِ سیستم‌عامل */
  reduceMotion: boolean
  /** هم‌ترازیِ بلندیِ ترک‌ها با گِینی که سرور اندازه گرفته */
  normalize: boolean
  /** ثانیه؛ صفر یعنی خاموش */
  crossfade: number
  /** فعال بودن میکس خودکار زمان‌بندی (Automix) */
  automix: boolean
  /** فعال بودن ترنزیشن‌های دی‌جی (سوئیپ فیلتر LPF و تعویض ساب‌بیس) */
  smartDj: boolean
  /** اکولایزر دقیق اندروید: ۷ باند دستی (۶۰Hz تا ۱۴kHz) به دسی‌بل */
  eqBands: number[]
  /** پد تون — x: tilt، y: contour؛ هر دو در بازهٔ ۵± گام */
  tone: { x: number; y: number }
  /** بالانس چپ/راست — ۱− تا ۱+ */
  balance: number
  eqEnabled: boolean
  spatialAudio: boolean
  nativeAudioEngine: NativeAudioEngineMode
  /** تقویتِ سراسریِ صدا به دسی‌بل — برای گوشی‌هایی که صدایشان کم است */
  boost: number
  /** چند دانلود هم‌زمان در فرانت فعال شود */
  maxConcurrentDownloads: number
  /** فرستادنِ خطاهای سمتِ کاربر به سرور */
  errorReporting: boolean
  setQuality: (q: Quality) => void
  setTheme: (theme: Theme) => void
  toggleTheme: () => void
  setLiquidGlass: (on: boolean) => void
  setReduceMotion: (on: boolean) => void
  setNormalize: (on: boolean) => void
  setCrossfade: (seconds: number) => void
  setAutomix: (on: boolean) => void
  setSmartDj: (on: boolean) => void
  setEqBands: (bands: number[]) => void
  setTone: (tone: { x: number; y: number }) => void
  setBalance: (balance: number) => void
  setEqEnabled: (on: boolean) => void
  setSpatialAudio: (on: boolean) => void
  setNativeAudioEngine: (mode: NativeAudioEngineMode) => void
  setBoost: (db: number) => void
  setMaxConcurrentDownloads: (n: number) => void
  setErrorReporting: (on: boolean) => void
}

const MEDIA_QUERY = '(prefers-color-scheme: light)'

function prefersLight(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  return window.matchMedia(MEDIA_QUERY).matches
}

/** `system` را به یکی از دو تمِ واقعی تبدیل می‌کند */
function resolveTheme(theme: Theme): ResolvedTheme {
  return theme === 'system' ? (prefersLight() ? 'light' : 'dark') : theme
}

let systemListenerAttached = false

function applyTheme(theme: Theme) {
  const resolved = resolveTheme(theme)
  if (typeof document !== 'undefined') {
    document.documentElement.dataset.theme = resolved
  }
  writeStored('theme', theme)
  // نوار وضعیت شفاف است و روی خودِ محتوا می‌افتد؛ اگر رنگِ آیکون‌هایش با تم
  // عوض نشود، در تمِ روشن ساعتِ سفید روی پس‌زمینه‌ی سفید ناپدید می‌شود
  syncStatusBar(resolved)
  attachSystemThemeListener(theme)
}

/*
 * در حالتِ `system` تم باید *زنده* عوض شود، نه فقط در رفرشِ بعدی.
 *
 * شنونده یک‌بار برای همیشه ثبت می‌شود و هر بار مقدارِ فعلیِ استور را می‌خواند؛
 * ثبت/برداشتنِ مکرر روی هر تعویضِ تم، فقط درِ فراموش‌کردنِ برداشتن را باز
 * می‌کند و به‌ازای هر سوییچ چند شنونده‌ی مرده می‌سازد.
 */
function attachSystemThemeListener(theme: Theme) {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
  if (theme !== 'system' || systemListenerAttached) return
  systemListenerAttached = true
  window.matchMedia(MEDIA_QUERY).addEventListener('change', () => {
    if (useSettings.getState().theme !== 'system') return
    const resolved = resolveTheme('system')
    if (typeof document !== 'undefined') document.documentElement.dataset.theme = resolved
    syncStatusBar(resolved)
  })
}

/*
 * در سطحِ ماژول خوانده می‌شود، پس نباید بتواند پرت کند — `readStoredAs` روی
 * مرورگری که ذخیره‌سازیِ سایت را بسته به پیش‌فرض برمی‌گردد به‌جای اینکه
 * بارگذاریِ اپ را متوقف کند.
 */
const initialTheme: Theme = readStoredAs<Theme>('theme', 'dark')
applyTheme(initialTheme)

const initialLiquidGlass = readStored('ui:liquidGlass') !== '0'
if (typeof document !== 'undefined') {
  document.documentElement.dataset.liquidGlass = initialLiquidGlass ? 'true' : 'false'
}

/*
 * کاهشِ انیمیشن پیش‌فرض خاموش است: یعنی «از سیستم پیروی کن».
 *
 * اگر روشن باشد، مقادیرِ `reducedMotion()` را برای همه‌ی انیمیشن‌های
 * جاوااسکریپتی (gsap، فنرِ تب‌بار، مارکی) به زور true می‌کند — و همین‌جا، پیش
 * از اولین رندر، اعمال می‌شود تا صفحه با انیمیشنی که کاربر نخواسته شروع نشود.
 */
const initialReduceMotion = readStored('ui:reduceMotion') === '1'
setReducedMotionOverride(initialReduceMotion ? true : null)

/*
 * گزارشِ خطا پیش‌فرض روشن است — بدونش هیچ‌وقت نمی‌فهمیم روی کدام گوشی چه
 * ترکِ صفحه را خوابانده. اما باید *قبل از* اولین خطا اعمال شود، وگرنه یک خطای
 * زودهنگام از تنظیمِ خاموش رد می‌شود.
 */
const initialErrorReporting = readStored('privacy:errorReports') !== '0'
setErrorReportingEnabled(initialErrorReporting)

/*
 * مهاجرت اکولایزر: کلیدهای قدیمی (پری‌ست ۵ بانده) به باندهای ۷تایی چیدمان
 * تازه تبدیل و با کلیدهای جدید ذخیره می‌شوند؛ کلید قدیمی پاک می‌شود.
 * نگاشتِ نزدیک‌ترین باند: ۶۰→۶۰، ۲۳۰→۱۵۰، ۹۱۰→۱۰۰۰، ۳۶۰۰→۲۵۰۰، ۱۴۰۰۰→۱۴۰۰۰.
 */
const LEGACY_BAND_TO_MANUAL = [0, 1, 3, 4, 6]
function migrateEqSettings(): { eqBands: number[]; tone: { x: number; y: number }; balance: number } {
  const storedBands = readStored('audio:eqBands')
  if (storedBands !== null) {
    try {
      const parsed = JSON.parse(storedBands) as number[]
      if (Array.isArray(parsed) && parsed.length === 7) {
        let tone = { x: 0, y: 0 }
        const storedTone = readStored('audio:tone')
        if (storedTone !== null) {
          try {
            const parsedTone = JSON.parse(storedTone) as { x?: number; y?: number }
            tone = { x: parsedTone.x ?? 0, y: parsedTone.y ?? 0 }
          } catch {
            tone = { x: 0, y: 0 }
          }
        }
        return {
          eqBands: parsed,
          tone,
          balance: readStoredNumber('audio:balance', 0, { min: -1, max: 1 }),
        }
      }
    } catch {
      // داده خراب — از مسیر مهاجرت قدیمی می‌رویم
    }
  }

  const oldPreset = readStoredAs<'off' | 'bass' | 'vocal' | 'treble' | 'loud'>('audio:eq', 'off')
  const oldValues: Record<string, number[]> = {
    off: [0, 0, 0, 0, 0],
    bass: [6, 3, 0, -1, -1],
    vocal: [-2, -1, 4, 3, 0],
    treble: [-2, -1, 0, 3, 6],
    loud: [5, 1, -2, 2, 5],
  }
  const bands = [0, 0, 0, 0, 0, 0, 0]
  const values = oldValues[oldPreset]
  if (values) {
    values.forEach((v, i) => {
      const idx = LEGACY_BAND_TO_MANUAL[i]
      if (idx !== undefined) bands[idx] = v
    })
  }
  // مهاجرتِ زودنویس: مقدارِ تبدیل‌شده همان لحظه ذخیره می‌شود تا خواندنِ
  // بعدی از کلید جدید برود و این تبدیل یک‌بار برای همیشه تمام شود
  writeStored('audio:eqBands', JSON.stringify(bands))
  writeStored('audio:tone', JSON.stringify({ x: 0, y: 0 }))
  writeStored('audio:balance', '0')
  removeStored('audio:eq')
  return { eqBands: bands, tone: { x: 0, y: 0 }, balance: 0 }
}

const migratedEq = migrateEqSettings()

// پیش‌فرضِ نرمال‌سازی روشن است: بدون آن اولین چیزی که کاربر از یک صفِ مخلوط
// می‌شنود همان جهش‌های صداست. کراس‌فید ولی خاموش می‌ماند — روی آلبومی که خودش
// گپ‌لس است، محوکردنِ ترک‌ها چیزی را خراب می‌کند که درست بوده.
const storedEqEnabled = readStored('audio:eqEnabled')
const initialEqEnabled =
  storedEqEnabled !== null ? storedEqEnabled === '1' : matchingPreset(migratedEq.eqBands) !== 'FLAT'

export const useSettings = create<SettingsState>((set, get) => ({
  quality: readStoredAs<Quality>('quality', '320'),
  theme: initialTheme,
  liquidGlass: initialLiquidGlass,
  reduceMotion: initialReduceMotion,
  normalize: readStored('audio:normalize') !== '0',
  crossfade: readStoredNumber('audio:crossfade', 0, { max: MAX_CROSSFADE }),
  automix: readStored('audio:automix') !== '0',
  smartDj: readStored('audio:smartDj') !== '0',
  eqBands: migratedEq.eqBands,
  tone: migratedEq.tone,
  balance: migratedEq.balance,
  eqEnabled: initialEqEnabled,
  spatialAudio: readStored('audio:spatial') === '1',
  nativeAudioEngine: readStoredAs<NativeAudioEngineMode>('audio:nativeEngine', 'auto'),
  boost: readStoredNumber('audio:boost', 0, { min: 0, max: MAX_BOOST_DB }),
  maxConcurrentDownloads: readStoredNumber('downloads:maxConcurrent', 3, {
    min: MIN_CONCURRENT_DOWNLOADS,
    max: MAX_CONCURRENT_DOWNLOADS,
  }),
  errorReporting: initialErrorReporting,

  setQuality: (quality) => {
    writeStored('quality', quality)
    set({ quality })
  },

  setTheme: (theme) => {
    applyTheme(theme)
    set({ theme })
  },

  toggleTheme: () => {
    /*
     * از حالتِ `system` هم با یک ضربه باید به یک تمِ واقعی رسید — وگرنه
     * دکمه‌ی هدر بی‌اثر به‌نظر می‌رسد تا وقتی کاربر برود داخلِ تنظیمات.
     * مقصد، تمِ *مخالفِ آنیِ فعلی* است تا عوض‌شدنش دیده شود.
     */
    const current = get().theme
    const next: Theme = resolveTheme(current) === 'dark' ? 'light' : 'dark'
    applyTheme(next)
    set({ theme: next })
  },

  setLiquidGlass: (on) => {
    writeStored('ui:liquidGlass', on ? '1' : '0')
    if (typeof document !== 'undefined') {
      document.documentElement.dataset.liquidGlass = on ? 'true' : 'false'
    }
    set({ liquidGlass: on })
  },

  setReduceMotion: (on) => {
    writeStored('ui:reduceMotion', on ? '1' : '0')
    // `null` یعنی «از سیستم بپرس» — همان رفتارِ قبل از وجودِ این تنظیم
    setReducedMotionOverride(on ? true : null)
    set({ reduceMotion: on })
  },

  setNormalize: (on) => {
    writeStored('audio:normalize', on ? '1' : '0')
    engine.setNormalize(on)
    set({ normalize: on })
  },

  setCrossfade: (seconds) => {
    const value = Math.max(0, Math.min(MAX_CROSSFADE, Math.round(seconds)))
    writeStored('audio:crossfade', String(value))
    engine.setCrossfade(value)
    nativeSetCrossfade(value)
    set({ crossfade: value })
  },

  setAutomix: (on) => {
    writeStored('audio:automix', on ? '1' : '0')
    engine.setAutomix(on)
    set({ automix: on })
  },

  setSmartDj: (on) => {
    writeStored('audio:smartDj', on ? '1' : '0')
    engine.setSmartDj(on)
    set({ smartDj: on })
  },

  setEqBands: (bands) => {
    const state = get()
    const value = bands.map((b) => Math.max(-MANUAL_RANGE_DB, Math.min(MANUAL_RANGE_DB, Math.round(b * 2) / 2)))
    writeStored('audio:eqBands', JSON.stringify(value))
    engine.setEq7({ bandsDb: value, tone: state.tone, balance: state.balance }, state.eqEnabled)
    nativeSetEqualizer(state.eqEnabled, value)
    set({ eqBands: value })
  },

  setTone: (tone) => {
    const state = get()
    const value = {
      x: Math.max(-5, Math.min(5, Math.round(tone.x))),
      y: Math.max(-5, Math.min(5, Math.round(tone.y))),
    }
    writeStored('audio:tone', JSON.stringify(value))
    engine.setEq7({ bandsDb: state.eqBands, tone: value, balance: state.balance }, state.eqEnabled)
    set({ tone: value })
  },

  setBalance: (balance) => {
    const state = get()
    const value = Math.max(-1, Math.min(1, balance))
    writeStored('audio:balance', String(value))
    engine.setEq7({ bandsDb: state.eqBands, tone: state.tone, balance: value }, state.eqEnabled)
    set({ balance: value })
  },

  setEqEnabled: (on) => {
    writeStored('audio:eqEnabled', on ? '1' : '0')
    const state = get()
    engine.setEq7({ bandsDb: state.eqBands, tone: state.tone, balance: state.balance }, on)
    nativeSetEqualizer(on, on ? state.eqBands : undefined)
    set({ eqEnabled: on })
  },

  setSpatialAudio: (on) => {
    writeStored('audio:spatial', on ? '1' : '0')
    // حالا روی وب هم واقعاً اثر می‌گذارد، نه فقط در اپ اندروید
    engine.setSpatialAudio(on)
    nativeSetSpatialAudio(on)
    set({ spatialAudio: on })
  },

  setNativeAudioEngine: (mode) => {
    writeStored('audio:nativeEngine', mode)
    set({ nativeAudioEngine: mode })
  },

  setBoost: (db) => {
    const value = Math.max(0, Math.min(MAX_BOOST_DB, Math.round(db)))
    writeStored('audio:boost', String(value))
    engine.setBoost(value)
    set({ boost: value })
  },

  /*
   * فقط مقدار را ذخیره می‌کند.
   *
   * صدا زدنِ `useDownloads.getState().pump()` این‌جا یعنی یک importِ حلقه‌ای
   * (`downloads` هم به `settings` نیاز دارد) — پس کنش در UI صدا زده می‌شود.
   */
  setMaxConcurrentDownloads: (n) => {
    const value = Math.max(
      MIN_CONCURRENT_DOWNLOADS,
      Math.min(MAX_CONCURRENT_DOWNLOADS, Math.round(n)),
    )
    writeStored('downloads:maxConcurrent', String(value))
    set({ maxConcurrentDownloads: value })
  },

  setErrorReporting: (on) => {
    writeStored('privacy:errorReports', on ? '1' : '0')
    setErrorReportingEnabled(on)
    set({ errorReporting: on })
  },
}))
