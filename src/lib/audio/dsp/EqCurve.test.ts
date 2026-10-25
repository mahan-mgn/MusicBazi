import { describe, expect, it } from 'vitest'
import {
  combineCurves,
  EQ_SLOTS,
  flatCurve,
  MANUAL_BANDS_HZ,
  manualCurve,
  sectionGainDb,
  SLOTS,
  TONE_DB_PER_STEP,
  TONE_STEPS,
  toneCurve,
} from './EqCurve'
import { EQ_PRESETS_DB, matchingPreset } from './EqPresets'

describe('چیدمان اکولایزر (EqLayout)', () => {
  it('۱۰ اسلات دارد: ۷ باند دستی + ۳ اسلات پد تون', () => {
    expect(EQ_SLOTS).toHaveLength(SLOTS)
    expect(MANUAL_BANDS_HZ).toEqual([60, 150, 400, 1000, 2500, 6000, 14000])
  })

  it('لبه‌های باند دستی shelf و وسط‌ها bell هستند', () => {
    expect(EQ_SLOTS[0].kind).toBe('LOW_SHELF')
    expect(EQ_SLOTS[6].kind).toBe('HIGH_SHELF')
    expect(EQ_SLOTS[3].kind).toBe('BELL')
  })

  it('پد تون: shelf در ۲۵۰/۴۰۰۰ و bell در ۱۰۰۰', () => {
    expect(EQ_SLOTS[7]).toMatchObject({ kind: 'LOW_SHELF', frequencyHz: 250 })
    expect(EQ_SLOTS[8]).toMatchObject({ kind: 'BELL', frequencyHz: 1000 })
    expect(EQ_SLOTS[9]).toMatchObject({ kind: 'HIGH_SHELF', frequencyHz: 4000 })
  })
})

describe('پاسخ بزرگیِ سکشن‌ها (sectionGainDb)', () => {
  it('گین صفر یعنی سهم صفر', () => {
    expect(sectionGainDb(EQ_SLOTS[3], 0, 1, 1000)).toBe(0)
  })

  it('bell روی فرکانس مرکزی‌اش دقیقاً همان گین خواسته‌شده را می‌دهد', () => {
    const bell = EQ_SLOTS[3] // ۱۰۰۰Hz
    for (const gain of [3, 6, -4.5, 12]) {
      expect(sectionGainDb(bell, gain, 1, 1000)).toBeCloseTo(gain, 4)
    }
  })

  it('bell دور از مرکز به صفر میل می‌کند', () => {
    const bell = EQ_SLOTS[3]
    // یک دهه بالاتر با Q=1: اثر قابل‌توجه ولی کوچک
    const far = sectionGainDb(bell, 12, 1, 10_000)
    expect(Math.abs(far)).toBeLessThan(6)
  })

  it('low shelf: در گوشه +۳dB و در فرکانس‌های پایین‌تر به سمت گین هدف می‌رود', () => {
    const shelf = EQ_SLOTS[0] // ۶۰Hz
    // تعریف کلاسیک shelf: در فرکانس گوشه نیمی از گین اعمال شده است
    expect(sectionGainDb(shelf, 6, 0.707, 60)).toBeCloseTo(3, 1)
    // پایین‌تر از گوشه، به مجانب (۶dB) نزدیک می‌شود
    expect(sectionGainDb(shelf, 6, 0.707, 20)).toBeCloseTo(6, 0)
    expect(sectionGainDb(shelf, 6, 0.707, 600)).toBeCloseTo(0, 0)
    // هرچه پایین‌تر، نزدیک‌تر به هدف
    expect(sectionGainDb(shelf, 6, 0.707, 10)).toBeGreaterThan(sectionGainDb(shelf, 6, 0.707, 40))
  })

  it('high shelf آینهٔ low shelf است — با مجانبِ تدریجی فرمول shelf', () => {
    const shelf = EQ_SLOTS[6] // ۱۴kHz
    // یک اکتاو بالای گوشه هنوز به مجانب نرسیده — این رفتار خود فرمول است
    const near = sectionGainDb(shelf, 5, 0.707, 19_000)
    expect(near).toBeGreaterThan(3.5)
    expect(sectionGainDb(shelf, 5, 0.707, 1_400)).toBeCloseTo(0, 0)
    // دورتر از گوشه، به هدف نزدیک‌تر
    expect(sectionGainDb(shelf, 5, 0.707, 60_000)).toBeCloseTo(5, 0)
    expect(near).toBeLessThan(sectionGainDb(shelf, 5, 0.707, 60_000))
  })
})

describe('preamp جبرانی', () => {
  it('منحنی تخت preamp صفر می‌خواهد', () => {
    const flat = flatCurve()
    expect(flat.preampDb).toBeCloseTo(0, 3)
  })

  it('تقویتِ همهٔ باندها preamp منفی می‌خواهد', () => {
    const curve = manualCurve([12, 12, 12, 12, 12, 12, 12])
    expect(curve.preampDb).toBeLessThan(-11)
  })

  it('preamp دقیقاً اوجِ منحنی را خنثی می‌کند — اوجِ کل روی ۰dB می‌نشیند', () => {
    const curve = manualCurve([8, -3, 5, 0, 2, 6, 1])
    // اوج جمعِ سکشن‌ها روی نقاط پاسخ نباید از |preamp| بیشتر شود
    let peak = -Infinity
    for (let point = 0; point < 96; point++) {
      const hz = 20 * Math.pow(1000, point / 95)
      let sum = 0
      for (let slot = 0; slot < SLOTS; slot++) {
        sum += sectionGainDb(EQ_SLOTS[slot], curve.gainsDb[slot], curve.qs[slot], hz)
      }
      peak = Math.max(peak, sum)
    }
    expect(peak + curve.preampDb).toBeCloseTo(0, 3)
  })

  it('تضعیفِ باندها preamp صفر می‌خواهد — هیچ‌چیز کلیپ نمی‌شود', () => {
    const curve = manualCurve([-6, -4, -2, 0, 0, -1, -3])
    expect(curve.preampDb).toBeCloseTo(0, 3)
  })
})

describe('منحنی دستی و پد تون', () => {
  it('manualCurve باندها را کلمپ می‌کند و Q دستی را می‌گذارد', () => {
    const curve = manualCurve([20, -20, 3, 0, 0, 0, 0])
    expect(curve.gainsDb[0]).toBe(12)
    expect(curve.gainsDb[1]).toBe(-12)
    expect(curve.qs[2]).toBe(1)
    // اسلات‌های پد تون دست‌نخورده
    expect(curve.gainsDb[8]).toBe(0)
  })

  it('toneCurve: tilt مثبت زیرِ را بالا و زیرِ چپ را پایین می‌برد', () => {
    const curve = toneCurve(TONE_STEPS, 0, false)
    expect(curve.gainsDb[7]).toBeCloseTo(-TONE_STEPS * TONE_DB_PER_STEP)
    expect(curve.gainsDb[9]).toBeCloseTo(TONE_STEPS * TONE_DB_PER_STEP)
    expect(curve.gainsDb[8]).toBe(0)
  })

  it('toneCurve: contour مثبت mid را بالا می‌برد', () => {
    const curve = toneCurve(0, 3, true)
    expect(curve.gainsDb[8]).toBeCloseTo(3 * TONE_DB_PER_STEP)
  })

  it('combineCurves جمع دسی‌بلی اسلات‌ها و preamp تازه است', () => {
    const manual = manualCurve([4, 0, 0, 0, 0, 0, 0])
    const tone = toneCurve(0, 2, false)
    const combined = combineCurves(manual, tone)
    expect(combined.gainsDb[0]).toBe(4)
    expect(combined.gainsDb[8]).toBeCloseTo(2 * TONE_DB_PER_STEP)
    expect(combined.preampDb).toBeLessThanOrEqual(0)
  })
})

describe('پری‌ست‌ها', () => {
  it('۱۶ پری‌ست مقدار + سفارشی بدون جدول', () => {
    let withValues = 0
    for (const [name, bands] of Object.entries(EQ_PRESETS_DB)) {
      if (name === 'CUSTOM') {
        expect(bands).toBeNull()
      } else {
        expect(bands, name).toHaveLength(7)
        withValues++
      }
    }
    expect(withValues).toBe(16)
  })

  it('matchingPreset پری‌ست دقیق را می‌شناسد', () => {
    expect(matchingPreset([0, 0, 0, 0, 0, 0, 0])).toBe('FLAT')
    expect(matchingPreset([6, 4, 1.5, 0, 0, 0, 0])).toBe('BASS_BOOST')
    expect(matchingPreset([-5, -2.5, 1.5, 4, 3.5, 1.5, -2])).toBe('SPOKEN_WORD')
  })

  it('اختلافِ زیر آستانه هم پری‌ست حساب می‌شود — بالای آستنه نه', () => {
    expect(matchingPreset([0.04, 0, 0, 0, 0, 0, 0])).toBe('FLAT')
    expect(matchingPreset([0.06, 0, 0, 0, 0, 0, 0])).toBe('CUSTOM')
  })

  it('طولِ اشتباه یا ترکیب جدید = سفارشی', () => {
    expect(matchingPreset([1, 2, 3])).toBe('CUSTOM')
    expect(matchingPreset([1, 2, 3, 4, 5, 6, 7])).toBe('CUSTOM')
  })

  it('پری‌ست‌های boost/cut آینهٔ هم‌اند', () => {
    const boost = EQ_PRESETS_DB.BASS_BOOST!
    const cut = EQ_PRESETS_DB.BASS_CUT!
    for (let i = 0; i < 7; i++) expect(boost[i]).toBeCloseTo(-cut[i], 6)
  })
})
