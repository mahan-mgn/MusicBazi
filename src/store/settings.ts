import { create } from 'zustand'
import { engine, MAX_BOOST_DB, type EqPreset } from '../lib/audioEngine'
import { nativeSetCrossfade, nativeSetEqualizer, nativeSetSpatialAudio, syncStatusBar } from '../lib/native'
import { readStored, readStoredAs, readStoredNumber, writeStored } from '../lib/storage'
import type { Quality } from '../lib/types'

type Theme = 'dark' | 'light'
export type NativeAudioEngineMode = 'auto' | 'on' | 'off'

/** بیشترین کراس‌فیدِ مجاز (ثانیه) — بالاتر از این، دو ترک روی هم می‌مانند نه محو */
export const MAX_CROSSFADE = 12

interface SettingsState {
  quality: Quality
  theme: Theme
  /** فعال‌بودنِ شیشه مایع (Liquid Glass) مطابق با BitChord */
  liquidGlass: boolean
  /** هم‌ترازیِ بلندیِ ترک‌ها با گِینی که سرور اندازه گرفته */
  normalize: boolean
  /** ثانیه؛ صفر یعنی خاموش */
  crossfade: number
  eq: EqPreset
  spatialAudio: boolean
  nativeAudioEngine: NativeAudioEngineMode
  /** تقویتِ سراسریِ صدا به دسی‌بل — برای گوشی‌هایی که صدایشان کم است */
  boost: number
  setQuality: (q: Quality) => void
  toggleTheme: () => void
  setLiquidGlass: (on: boolean) => void
  setNormalize: (on: boolean) => void
  setCrossfade: (seconds: number) => void
  setEq: (preset: EqPreset) => void
  setSpatialAudio: (on: boolean) => void
  setNativeAudioEngine: (mode: NativeAudioEngineMode) => void
  setBoost: (db: number) => void
}

function applyTheme(theme: Theme) {
  if (typeof document !== 'undefined') {
    document.documentElement.dataset.theme = theme
  }
  writeStored('theme', theme)
  // نوار وضعیت شفاف است و روی خودِ محتوا می‌افتد؛ اگر رنگِ آیکون‌هایش با تم
  // عوض نشود، در تمِ روشن ساعتِ سفید روی پس‌زمینه‌ی سفید ناپدید می‌شود
  syncStatusBar(theme)
}

/*
 * در سطحِ ماژول خوانده می‌شود، پس نباید بتواند پرت کند — `readStoredAs` روی
 * مرورگری که ذخیره‌سازیِ سایت را بسته به پیش‌فرض برمی‌گردد به‌جای اینکه
 * بارگذاریِ اپ را متوقف کند.
 */
const initialTheme: Theme = readStoredAs<Theme>('theme', 'dark') === 'light' ? 'light' : 'dark'
applyTheme(initialTheme)

const initialLiquidGlass = readStored('ui:liquidGlass') !== '0'
if (typeof document !== 'undefined') {
  document.documentElement.dataset.liquidGlass = initialLiquidGlass ? 'true' : 'false'
}

// پیش‌فرضِ نرمال‌سازی روشن است: بدون آن اولین چیزی که کاربر از یک صفِ مخلوط
// می‌شنود همان جهش‌های صداست. کراس‌فید ولی خاموش می‌ماند — روی آلبومی که خودش
// گپلس است، محوکردنِ ترک‌ها چیزی را خراب می‌کند که درست بوده.
export const useSettings = create<SettingsState>((set, get) => ({
  quality: readStoredAs<Quality>('quality', '320'),
  theme: initialTheme,
  liquidGlass: initialLiquidGlass,
  normalize: readStored('audio:normalize') !== '0',
  crossfade: readStoredNumber('audio:crossfade', 0, { max: MAX_CROSSFADE }),
  eq: readStoredAs<EqPreset>('audio:eq', 'off'),
  spatialAudio: readStored('audio:spatial') === '1',
  nativeAudioEngine: readStoredAs<NativeAudioEngineMode>('audio:nativeEngine', 'auto'),
  boost: readStoredNumber('audio:boost', 0, { min: 0, max: MAX_BOOST_DB }),

  setQuality: (quality) => {
    writeStored('quality', quality)
    set({ quality })
  },

  toggleTheme: () => {
    const theme = get().theme === 'dark' ? 'light' : 'dark'
    applyTheme(theme)
    set({ theme })
  },

  setLiquidGlass: (on) => {
    writeStored('ui:liquidGlass', on ? '1' : '0')
    if (typeof document !== 'undefined') {
      document.documentElement.dataset.liquidGlass = on ? 'true' : 'false'
    }
    set({ liquidGlass: on })
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

  setEq: (preset) => {
    writeStored('audio:eq', preset)
    engine.setEq(preset)
    nativeSetEqualizer(preset !== 'off')
    set({ eq: preset })
  },

  setSpatialAudio: (on) => {
    writeStored('audio:spatial', on ? '1' : '0')
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
}))
