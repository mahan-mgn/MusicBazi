/*
 * پورت `dsp/EqualizerCurve.kt` اندروید — چیدمان و ریاضیِ اکولایزر.
 *
 * Copyright (C) 2024-2026 Kushagra Singh / BitChord Contributors, GPL-3.0
 * (پورت‌شده به Music Bazi — همین پرونده هم تحت GPL-3.0 منتشر می‌شود)
 */

/** شکلِ یک فیلتر در چیدمان */
export type FilterKind = 'BELL' | 'LOW_SHELF' | 'HIGH_SHELF'

/** هویتِ ثابتِ یک اسلات: شکل و جای آن روی طیف */
export interface FilterSlot {
  kind: FilterKind
  frequencyHz: number
}

/**
 * هر فیلتری که دو تب اکولایزر می‌خواهند، در یک فهرست ثابت.
 *
 * ۷ اسلات اول «دستی»اند (اسلایدرها)، ۳ اسلات آخر پدِ تون (tilt/contour).
 */
export const MANUAL_BANDS_HZ = [60, 150, 400, 1_000, 2_500, 6_000, 14_000] as const

/**
 * به‌قدر کافی پهن تا همسایه‌ها را بپوشاند — مراکز حدود ۱٫۳ اکتاو فاصله دارند،
 * پس Q نزدیک ۱ یعنی بالا کشیدنِ همهٔ اسلایدرها کل باند را یکنواخت بالا می‌برد
 * نه اینکه بین باندها فرورفتگی (scalloping) بگذارد.
 */
export const MANUAL_Q = 1.0

export const MANUAL_FIRST = 0
export const MANUAL_COUNT = 7

/** اسلات‌های ۷..۹: جفتِ tilt پد تون و contour میانی آن */
export const TONE_LOW = 7
export const TONE_MID = 8
export const TONE_HIGH = 9

export const SLOTS = 10

export const EQ_SLOTS: FilterSlot[] = [
  ...MANUAL_BANDS_HZ.map((hz, index): FilterSlot => ({
    kind: index === 0 ? 'LOW_SHELF' : index === MANUAL_BANDS_HZ.length - 1 ? 'HIGH_SHELF' : 'BELL',
    frequencyHz: hz,
  })),
  { kind: 'LOW_SHELF', frequencyHz: 250 },
  { kind: 'BELL', frequencyHz: 1_000 },
  { kind: 'HIGH_SHELF', frequencyHz: 4_000 },
]

/** بردِ هر اسلایدر دستی، به دو طرف */
export const MANUAL_RANGE_DB = 12

/** تعداد گام‌های پد تون در هر محور */
export const TONE_STEPS = 5

/** دسی‌بل به‌ازای هر گام پد — گوشهٔ پد یعنی ±۶ دسی‌بل */
export const TONE_DB_PER_STEP = 1.2

/** فرکانس جفتِ tilt پد تون — برای توصیف UI */
export const TONE_TILT_HZ = [250, 4_000] as const

/**
 * یک تیونینگ، رندرشده: هر اسلات الان روی چیست.
 */
export interface EqCurve {
  gainsDb: Float32Array
  qs: Float32Array
  /**
   * تضعیفِ جبرانی، همیشه صفر یا منفی — طوری که اوجِ منحنی کلیپ نکند.
   */
  preampDb: number
}

export const SHELF_DEFAULT_Q = 0.707

function makeCurve(gainsDb: Float32Array, qs: Float32Array): EqCurve {
  return { gainsDb, qs, preampDb: preampFor(gainsDb, qs) }
}

/** منحنی تخت — همهٔ اسلات‌ها صفر */
export function flatCurve(): EqCurve {
  return makeCurve(new Float32Array(SLOTS), new Float32Array(SLOTS).fill(SHELF_DEFAULT_Q))
}

/** هفت اسلایدر، به‌صورت منحنی. اسلات‌های پد تون تخت می‌مانند. */
export function manualCurve(bandsDb: readonly number[]): EqCurve {
  const gains = new Float32Array(SLOTS)
  const qs = new Float32Array(SLOTS).fill(SHELF_DEFAULT_Q)
  for (let band = 0; band < MANUAL_COUNT; band++) {
    gains[MANUAL_FIRST + band] = clamp(
      bandsDb[band] ?? 0,
      -MANUAL_RANGE_DB,
      MANUAL_RANGE_DB,
    )
    qs[MANUAL_FIRST + band] = MANUAL_Q
  }
  return makeCurve(gains, qs)
}

/**
 * پد تون، به‌صورت منحنی. اسلات‌های دستی تخت می‌مانند.
 * x: tilt (−۵..۵، مثبت یعنی زیرِ بلندتر)، y: contour میانی (−۵..۵).
 */
export function toneCurve(x: number, y: number, focused: boolean): EqCurve {
  const gains = new Float32Array(SLOTS)
  const qs = new Float32Array(SLOTS).fill(SHELF_DEFAULT_Q)
  const tilt = clamp(x, -TONE_STEPS, TONE_STEPS) * TONE_DB_PER_STEP
  const contour = clamp(y, -TONE_STEPS, TONE_STEPS) * TONE_DB_PER_STEP

  gains[TONE_LOW] = -tilt
  gains[TONE_HIGH] = tilt
  gains[TONE_MID] = contour

  const shelfQ = focused ? 0.9 : 0.5
  const bellQ = focused ? 2.2 : 0.7
  qs[TONE_LOW] = shelfQ
  qs[TONE_HIGH] = shelfQ
  qs[TONE_MID] = bellQ
  return makeCurve(gains, qs)
}

/**
 * ترکیبِ دو منحنی (دستی + پد تون) — هر دو روی اسلات‌های جدا می‌نشینند پس
 * جمعِ دسی‌بلشان همان نتیجهٔ شنیداری است. preamp دوباره از روی مجموع
 * محاسبه می‌شود.
 */
export function combineCurves(manual: EqCurve, tone: EqCurve): EqCurve {
  const gains = new Float32Array(SLOTS)
  const qs = new Float32Array(SLOTS)
  for (let slot = 0; slot < SLOTS; slot++) {
    gains[slot] = manual.gainsDb[slot] + tone.gainsDb[slot]
    qs[slot] = manual.gainsDb[slot] !== 0 ? manual.qs[slot] : tone.qs[slot]
  }
  return makeCurve(gains, qs)
}

/** چند دسی‌بل باید منحنی پایین کشیده شود تا کلیپ نکند */
export function preampFor(gainsDb: Float32Array, qs: Float32Array): number {
  let peak = 0
  for (let point = 0; point < RESPONSE_POINTS; point++) {
    const hz = responseFrequency(point)
    let sum = 0
    for (let slot = 0; slot < SLOTS; slot++) {
      sum += sectionGainDb(EQ_SLOTS[slot], gainsDb[slot], qs[slot], hz)
    }
    if (sum > peak) peak = sum
  }
  return -peak
}

/** نقاط پاسخ، با فاصلهٔ لگاریتمی روی ۲۰Hz تا ۲۰kHz */
function responseFrequency(point: number): number {
  const fraction = point / (RESPONSE_POINTS - 1)
  return 20 * Math.pow(1_000, fraction)
}

/**
 * سهمِ یک سکشن در فرکانس hz، به دسی‌بل — پاسخ بزرگیِ دقیقِ سه نوع فیلتر
 * (همان فرمول‌های `sectionGainDb` اندروید؛ مرجعِ محاسبهٔ preamp و تست‌ها).
 */
export function sectionGainDb(slot: FilterSlot, gainDb: number, q: number, hz: number): number {
  if (Math.abs(gainDb) < 0.01) return 0
  const a = Math.pow(10, gainDb / 40)
  const a2 = a * a
  const x = hz / slot.frequencyHz
  const x2 = x * x
  const qq = q * q
  let magnitude: number
  switch (slot.kind) {
    case 'BELL': {
      const flat = (1 - x2) * (1 - x2)
      magnitude = Math.sqrt((flat + (x2 * a2) / qq) / (flat + x2 / (a2 * qq)))
      break
    }
    case 'LOW_SHELF': {
      const common = (x2 * a) / qq
      magnitude =
        a * Math.sqrt(((a - x2) * (a - x2) + common) / ((1 - a * x2) * (1 - a * x2) + common))
      break
    }
    case 'HIGH_SHELF': {
      const common = (x2 * a) / qq
      magnitude =
        a * Math.sqrt(((1 - a * x2) * (1 - a * x2) + common) / ((a - x2) * (a - x2) + common))
      break
    }
  }
  return 20 * Math.log10(magnitude)
}

const RESPONSE_POINTS = 96

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}
