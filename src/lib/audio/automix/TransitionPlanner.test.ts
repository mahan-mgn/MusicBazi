import { describe, expect, it } from 'vitest'
import {
  areHarmonicallyCompatible,
  areTemposClose,
  planTransition,
} from './TransitionPlanner'

describe('TransitionPlanner & Automix Engine', () => {
  it('areHarmonicallyCompatible: تشخیص کلیدهای سازگار روی چرخه پنجم‌ها', () => {
    // کلیدهای یکسان
    expect(areHarmonicallyCompatible('C', 'C')).toBe(true)
    expect(areHarmonicallyCompatible('A', 'A')).toBe(true)

    // فاصله پنجم درست (۷ نیم‌پرده: C -> G)
    expect(areHarmonicallyCompatible('C', 'G')).toBe(true)
    // فاصله چهارم درست (۵ نیم‌پرده: C -> F)
    expect(areHarmonicallyCompatible('C', 'F')).toBe(true)

    // کلیدهای ناهماهنگ و متضاد (مثلا C و F# که تریتون است)
    expect(areHarmonicallyCompatible('C', 'F#')).toBe(false)
    expect(areHarmonicallyCompatible(undefined, 'C')).toBe(false)
  })

  it('areTemposClose: تشخیص تمپوهای نزدیک با تراز اکتاوی', () => {
    // تمپوهای نزدیک
    expect(areTemposClose(120, 124)).toBe(true)
    expect(areTemposClose(128, 125)).toBe(true)

    // تراز اکتاوی (مثلا 70 BPM و 140 BPM)
    expect(areTemposClose(70, 140)).toBe(true)
    expect(areTemposClose(130, 65)).toBe(true)

    // تمپوهای کاملاً دور
    expect(areTemposClose(90, 130)).toBe(false)
    expect(areTemposClose(0, 120)).toBe(false)
  })

  it('planTransition: اگر کراس‌فید خاموش باشد، خروجی GAPLESS است', () => {
    const plan = planTransition(
      { id: 'track1', durationMs: 200_000 },
      { id: 'track2', durationMs: 180_000 },
      0,
    )
    expect(plan.transitionStyle).toBe('GAPLESS')
    expect(plan.fadeSeconds).toBe(0)
    expect(plan.bassSwap).toBe(false)
  })

  it('planTransition: تمپوی یکسان باعث انتخاب DJ_BLEND با Bass Swap می‌شود', () => {
    const plan = planTransition(
      { id: 't1', durationMs: 240_000, bpm: 124, key: 'C' },
      { id: 't2', durationMs: 210_000, bpm: 126, key: 'G' },
      8,
      true,
    )
    expect(plan.transitionStyle).toBe('DJ_BLEND')
    expect(plan.bassSwap).toBe(true)
    expect(plan.bassSwapFraction).toBe(0.5)
    expect(plan.filterVariant).toBe('BASS_HANDOFF') // چون کلیدها سازگارند
  })

  it('planTransition: تمپوی متفاوت باعث انتخاب DJ_FILTER می‌شود', () => {
    const plan = planTransition(
      { id: 't1', durationMs: 240_000, bpm: 85, key: 'C' },
      { id: 't2', durationMs: 210_000, bpm: 135, key: 'D' },
      6,
      true,
    )
    expect(plan.transitionStyle).toBe('DJ_FILTER')
    expect(plan.bassSwap).toBe(false)
    expect(plan.filterVariant).toBe('SWEEP')
  })

  it('planTransition: اگر smartDj غیرفعال باشد، همیشه فید تمیز EQUAL_POWER استفاده می‌شود', () => {
    // تمپو یکسان ولی smartDj خاموش: نباید فیلتر دی‌جی یا Bass Swap بخورد
    const plan = planTransition(
      { id: 't1', durationMs: 240_000, bpm: 124, key: 'C' },
      { id: 't2', durationMs: 210_000, bpm: 126, key: 'G' },
      8,
      { automix: true, smartDj: false },
    )
    expect(plan.transitionStyle).toBe('EQUAL_POWER')
    expect(plan.bassSwap).toBe(false)
  })

  it('planTransition: اگر automix غیرفعال باشد، دقیقاً از زمان کراس‌فید کاربر استفاده می‌شود', () => {
    const plan = planTransition(
      { id: 't1', durationMs: 240_000, bpm: 120 },
      { id: 't2', durationMs: 210_000, bpm: 120 },
      3, // ۳ ثانیه، کمتر از حداقل هوشمند ۴ ثانیه
      { automix: false, smartDj: true },
    )
    expect(plan.fadeSeconds).toBe(3)
  })

  it('planTransition: محتوای گفتاری و لایو به کراس‌فید استاندارد تنزل می‌یابد', () => {
    const plan = planTransition(
      { id: 't1', durationMs: 300_000, title: 'Podcast Episode 42', bpm: 120 },
      { id: 't2', durationMs: 200_000, bpm: 120 },
      5,
      true,
    )
    expect(plan.transitionStyle).toBe('EQUAL_POWER')
  })
})
