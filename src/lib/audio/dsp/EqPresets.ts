/*
 * پورت `dsp/EqualizerPreset.kt` اندروید — ۱۶ پری‌ست استاندارد + سفارشی.
 *
 * Copyright (C) 2024-2026 Kushagra Singh / BitChord Contributors, GPL-3.0
 * (پورت‌شده به Music Bazi — همین پرونده هم تحت GPL-3.0 منتشر می‌شود)
 *
 * هر پری‌ست ۷ عدد دسی‌بل برای هفت باند دستی است (۶۰Hz تا ۱۴kHz).
 */

export const EQ_PRESET_ORDER = [
  'FLAT',
  'ACOUSTIC',
  'BASS_BOOST',
  'BASS_CUT',
  'VOCAL',
  'TREBLE_BOOST',
  'TREBLE_CUT',
  'LOUDNESS',
  'SPOKEN_WORD',
  'ELECTRONIC',
  'ROCK',
  'HIP_HOP',
  'JAZZ',
  'CLASSICAL',
  'SMALL_SPEAKERS',
  'LATE_NIGHT',
  'CUSTOM',
] as const

export type EqPresetName = (typeof EQ_PRESET_ORDER)[number]

/** باندهای هر پری‌ست به دسی‌بل — همان جدول `EqualizerPreset.kt` */
export const EQ_PRESETS_DB: Record<EqPresetName, readonly number[] | null> = {
  FLAT: [0, 0, 0, 0, 0, 0, 0],
  ACOUSTIC: [3, 1.5, 0, 1.5, 2.5, 2, 1],
  BASS_BOOST: [6, 4, 1.5, 0, 0, 0, 0],
  BASS_CUT: [-6, -4, -1.5, 0, 0, 0, 0],
  VOCAL: [-3, -1.5, 1, 3.5, 3, 1, -1],
  TREBLE_BOOST: [0, 0, 0, 0, 1.5, 3.5, 5],
  TREBLE_CUT: [0, 0, 0, 0, -1.5, -3.5, -5],
  LOUDNESS: [6, 3.5, 0, -1.5, -1, 2, 5],
  SPOKEN_WORD: [-5, -2.5, 1.5, 4, 3.5, 1.5, -2],
  ELECTRONIC: [5, 3, -1, 0, 1, 3, 4],
  ROCK: [4, 2.5, -1, -1.5, 1, 3, 3.5],
  HIP_HOP: [6, 4, 0.5, -1, 0.5, 2, 2.5],
  JAZZ: [3, 1.5, 0, 1, 1.5, 2, 2.5],
  CLASSICAL: [3, 2, 0, 0, 1, 2.5, 3],
  SMALL_SPEAKERS: [5, 4, 2, 0.5, 0, -1, -2],
  LATE_NIGHT: [3, 1, 0, 1.5, 1, -1, -3],
  // سفارشی جدول ندارد — باندهایش را کاربر می‌سازد
  CUSTOM: null,
}

/**
 * اگر باندها دقیقاً یکی از پری‌ست‌ها باشند همان برچسب را می‌دهد، وگرنه
 * «سفارشی» — همان `matching` کاتلین با آستانهٔ ۰٫۰۵ دسی‌بل.
 */
export function matchingPreset(bandsDb: readonly number[]): EqPresetName {
  for (const name of EQ_PRESET_ORDER) {
    const bands = EQ_PRESETS_DB[name]
    if (!bands || bands.length !== bandsDb.length) continue
    let all = true
    for (let i = 0; i < bands.length; i++) {
      if (Math.abs(bands[i] - bandsDb[i]) >= 0.05) {
        all = false
        break
      }
    }
    if (all) return name
  }
  return 'CUSTOM'
}
