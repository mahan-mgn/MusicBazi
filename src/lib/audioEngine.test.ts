import { describe, expect, it } from 'vitest'
import {
  EQ_BANDS,
  EQ_PRESETS,
  gainFromDb,
  MAX_BOOST_DB,
  makeEqualPowerFadeInCurve,
  makeEqualPowerFadeOutCurve,
} from './audioEngine'

/**
 * خودِ موتور به Web Audio و DOM نیاز دارد و اینجا تست نمی‌شود؛ چیزی که تست
 * می‌شود ریاضیِ بلندی است — همان جایی که یک اشتباهِ ساده به صدای دو برابر یا
 * سکوت ختم می‌شود.
 */
describe('gainFromDb', () => {
  it('صفر دسی‌بل یعنی دست نزن', () => {
    expect(gainFromDb(0)).toBe(1)
  })

  it('هر شش دسی‌بل تقریباً دو برابرِ دامنه است', () => {
    expect(gainFromDb(6)).toBeCloseTo(2, 1)
    expect(gainFromDb(-6)).toBeCloseTo(0.5, 1)
  })

  it('منفی یعنی آرام‌تر، مثبت یعنی بلندتر', () => {
    expect(gainFromDb(-4.7)).toBeLessThan(1)
    expect(gainFromDb(3)).toBeGreaterThan(1)
  })

  it('هیچ‌وقت منفی نمی‌شود — گِینِ منفی یعنی وارونگیِ فاز، نه سکوت', () => {
    expect(gainFromDb(-60)).toBeGreaterThan(0)
  })
})

describe('پریست‌های اکولایزر', () => {
  it('به‌ازای هر باند یک عدد دارند', () => {
    for (const [name, values] of Object.entries(EQ_PRESETS)) {
      expect(values, name).toHaveLength(EQ_BANDS.length)
    }
  })

  it('«خنثی» واقعاً هیچ باندی را دست نمی‌زند', () => {
    expect(EQ_PRESETS.off.every((value) => value === 0)).toBe(true)
  })

  it('باندها از بم به زیر مرتب‌اند', () => {
    const sorted = [...EQ_BANDS].sort((a, b) => a - b)
    expect(EQ_BANDS).toEqual(sorted)
  })

  it('«بم» بم را بالا می‌برد و «زیر» زیر را', () => {
    expect(EQ_PRESETS.bass[0]).toBeGreaterThan(0)
    expect(EQ_PRESETS.treble[EQ_BANDS.length - 1]).toBeGreaterThan(0)
  })
})

describe('تقویتِ سراسری', () => {
  it('سقفش در بازه‌ی معقول است — بالای ۱۲ دسی‌بل تقریباً همیشه کلیپ است', () => {
    expect(MAX_BOOST_DB).toBeGreaterThan(0)
    expect(MAX_BOOST_DB).toBeLessThanOrEqual(12)
  })

  it('هم‌ترازی و تقویت ضربی ترکیب می‌شوند، نه جمعِ دسی‌بلی', () => {
    // چیزی که applyNormalize می‌سازد: gainFromDb(gainDb) * gainFromDb(boost)
    // معادلِ جمعِ دسی‌بل‌هاست؛ اگر روزی کسی اینجا min/max اشتباه بگذارد،
    // صدای کاربر چند دسی‌بل جابه‌جا می‌شود
    const gainDb = -3
    const boost = 6
    expect(gainFromDb(gainDb) * gainFromDb(boost)).toBeCloseTo(gainFromDb(gainDb + boost))
  })

  it('تقویتِ صفر چیزی را عوض نمی‌کند', () => {
    expect(gainFromDb(0)).toBe(1)
    expect(gainFromDb(-2) * gainFromDb(0)).toBeCloseTo(gainFromDb(-2))
  })
})

describe('منحنی‌های کراس‌فید توان-برابر (Equal-Power Curves)', () => {
  it('در تمام نقاط منحنی، مجموع توان دو سیگنال برابر با ۱ است (بدون افت دسی‌بل)', () => {
    const fadeOut = makeEqualPowerFadeOutCurve(64)
    const fadeIn = makeEqualPowerFadeInCurve(64)

    expect(fadeOut.length).toBe(64)
    expect(fadeIn.length).toBe(64)

    // در ابتدا: خروجی کامل (1.0)، ورودی صفر
    expect(fadeOut[0]).toBeCloseTo(1.0, 4)
    expect(fadeIn[0]).toBeCloseTo(0.0, 4)

    // در انتها: خروجی صفر، ورودی کامل (1.0)
    expect(fadeOut[63]).toBeCloseTo(0.0, 4)
    expect(fadeIn[63]).toBeCloseTo(1.0, 4)

    // در تمام ۶۴ نقطه: مجموع مربعات (توان آکوستیک) باید دقیقاً ۱ باشد
    for (let i = 0; i < 64; i++) {
      const power = fadeOut[i] * fadeOut[i] + fadeIn[i] * fadeIn[i]
      expect(power).toBeCloseTo(1.0, 4)
    }
  })
})
