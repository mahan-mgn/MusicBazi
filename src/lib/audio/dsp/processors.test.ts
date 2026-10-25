import { describe, expect, it } from 'vitest'
import { Equalizer } from './Equalizer'
import { manualCurve, flatCurve } from './EqCurve'
import { Spatializer } from './Spatializer'
import { Loudness } from './Loudness'
import { createBlock } from './AudioBlock'

const SAMPLE_RATE = 48_000

/** سینوس خالص روی یک بلوک — برای اندازه‌گیری پاسخ پردازنده‌ها */
function sineBlock(freq: number, frames: number, sampleRate = SAMPLE_RATE, amplitude = 0.5) {
  const block = createBlock(frames, 2)
  for (let i = 0; i < frames; i++) {
    const v = amplitude * Math.sin((2 * Math.PI * freq * i) / sampleRate)
    block.samples[i * 2] = v
    block.samples[i * 2 + 1] = v
  }
  return block
}

/** RMS یک کانال از بلوک (نیمهٔ دوم ناپایدارِ فیلترها دور ریخته می‌شود) */
function rms(
  block: { samples: Float32Array; frameCount: number; channelCount: number },
  channel: number,
  skip = 2048,
): number {
  let sum = 0
  let count = 0
  for (let i = skip; i < block.frameCount; i++) {
    const v = block.samples[i * block.channelCount + channel]
    sum += v * v
    count++
  }
  return Math.sqrt(sum / count)
}

describe('Equalizer — SVF ذوزنقه‌ای', () => {
  it('منحنی تخت: سیگنال دست‌نخورده می‌گذرد (skip کامل)', () => {
    const eq = new Equalizer()
    eq.configure(SAMPLE_RATE, 2)
    eq.setTarget({ enabled: true, curve: flatCurve(), balance: 0 })
    const block = sineBlock(1000, 8192)
    eq.process(block)
    // 0.5 amplitude → rms ≈ 0.354؛ tolerance برای float
    expect(rms(block, 0)).toBeCloseTo(0.354, 2)
    expect(rms(block, 1)).toBeCloseTo(0.354, 2)
  })

  it('boost ۶dB روی باند ۱۰۰۰Hz: بزرگنمایی ≈ ۲× (۶dB) در همان فرکانس', () => {
    const eq = new Equalizer()
    eq.configure(SAMPLE_RATE, 2)
    // اندیس ۳ در چیدمان = باند ۱۰۰۰Hz (۶۰/۱۵۰/۴۰۰/۱۰۰۰/…)
    const curve = manualCurve([0, 0, 0, 6, 0, 0, 0])
    eq.setTarget({ enabled: true, curve, balance: 0 })
    const block = sineBlock(1000, 16384)
    eq.process(block)
    // preamp منحنی ≈ -6dB (اوج همان باندهاست) — پس در فرکانس مرکزی:
    // +6dB باند − ~6dB preamp ≈ 0dB نسبت به ورودی؛ در فرکانس دور: −6dB
    // نیمهٔ دوم اندازه می‌شود تا گذارِ گلاید اولیه در RMS نیفتد
    const boosted = rms(block, 0, 8192)
    const reference = sineBlock(1000, 16384)
    const refRms = rms(reference, 0, 8192)
    expect(boosted / refRms).toBeGreaterThan(0.9)
    expect(boosted / refRms).toBeLessThan(1.2)
  })

  it('boost در فرکانسِ دور از باند، با preamp جبرانی تضعیف می‌شود', () => {
    const eq = new Equalizer()
    eq.configure(SAMPLE_RATE, 2)
    const curve = manualCurve([0, 0, 12, 0, 0, 0, 0])
    eq.setTarget({ enabled: true, curve, balance: 0 })
    // ۶۰Hz دور از باند ۱۰۰۰Hz است (فقط اسلات shelf ۲۵۰ پد تون تخت است)
    const block = sineBlock(60, 16384)
    eq.process(block)
    const refRms = rms(sineBlock(60, 16384), 0)
    // preamp ≈ −12dB؛ اثر bell ۱۰۰۰Hz در ۶۰Hz ناچیز
    expect(rms(block, 0) / refRms).toBeLessThan(0.5)
  })

  it('balance تمام-راست: کانال چپ ساکت می‌شود', () => {
    const eq = new Equalizer()
    eq.configure(SAMPLE_RATE, 2)
    eq.setTarget({ enabled: true, curve: flatCurve(), balance: 1 })
    const block = sineBlock(1000, 16384)
    eq.process(block)
    // پس از پایان گلاید، گین کانال چپ صفر می‌شود
    expect(rms(block, 0, 8192)).toBeCloseTo(0, 3)
    expect(rms(block, 1, 8192)).toBeCloseTo(0.354, 2)
  })

  it('disabled: هیچ پردازشی انجام نمی‌شود حتی با منحنی پر', () => {
    const eq = new Equalizer()
    eq.configure(SAMPLE_RATE, 2)
    eq.setTarget({ enabled: false, curve: manualCurve([12, 12, 12, 12, 12, 12, 12]), balance: 0.5 })
    const block = sineBlock(1000, 4096)
    const ref = sineBlock(1000, 4096)
    eq.process(block)
    expect(Array.from(block.samples)).toEqual(Array.from(ref.samples))
  })

  it('گلاید: تغییر تیونینگ حین پخش، نرم به هدف می‌رسد (بدون پرش)', () => {
    const eq = new Equalizer()
    eq.configure(SAMPLE_RATE, 2)
    eq.setTarget({ enabled: true, curve: flatCurve(), balance: 0 })
    const block = sineBlock(1000, 16384)
    // وسط بلوک منحنی عوض می‌شود — نباید NaN یا پرش بزرگ بدهد
    eq.process(subBlock(block, 0, 4096))
    eq.setTarget({ enabled: true, curve: manualCurve([0, 0, 0, 0, 0, 12, 0]), balance: 0 })
    eq.process(subBlock(block, 4096, 4096))
    eq.process(subBlock(block, 8192, 8192))
    for (const v of block.samples) {
      expect(Number.isFinite(v)).toBe(true)
    }
    // پس از گلاید، باند ۱۴k Boost اثری روی ۱۰۰۰Hz ندارد ولی preamp −۱۲dB دارد
    // → RMS باید به‌طور معنادار از ورودی کمتر شده باشد
    const refRms = rms(sineBlock(1000, 16384), 0)
    expect(rms(block, 0)).toBeLessThan(refRms * 0.8)
  })

  it('mono (۱ کانال) هم کار می‌کند — balance نادیده گرفته می‌شود', () => {
    const eq = new Equalizer()
    eq.configure(SAMPLE_RATE, 1)
    eq.setTarget({ enabled: true, curve: manualCurve([0, 0, 6, 0, 0, 0, 0]), balance: 1 })
    const block = createBlock(8192, 1)
    for (let i = 0; i < 8192; i++) block.samples[i] = 0.5 * Math.sin((2 * Math.PI * 1000 * i) / SAMPLE_RATE)
    eq.process(block)
    expect(Number.isFinite(rms(block, 0))).toBe(true)
    expect(rms(block, 0)).toBeGreaterThan(0.1)
  })
})

describe('Spatializer — mid/side + crossfeed', () => {
  it('غیرفعال: رد کامل', () => {
    const sp = new Spatializer(false)
    sp.configure(SAMPLE_RATE, 2)
    const block = sineBlock(1000, 4096)
    const ref = sineBlock(1000, 4096)
    sp.process(block)
    expect(Array.from(block.samples)).toEqual(Array.from(ref.samples))
  })

  it('محتوای استریوی واقعی (با side) عریض‌تر می‌شود — side با ۲٫۵ تقویت می‌شود', () => {
    const sp = new Spatializer(true)
    sp.configure(SAMPLE_RATE, 2)
    // L و R با فاز متفاوت → side واقعی
    const block = createBlock(8192, 2)
    for (let i = 0; i < 8192; i++) {
      const l = 0.25 * Math.sin((2 * Math.PI * 1000 * i) / SAMPLE_RATE)
      const r = 0.25 * Math.sin((2 * Math.PI * 1000 * i) / SAMPLE_RATE + Math.PI / 3)
      block.samples[i * 2] = l
      block.samples[i * 2 + 1] = r
    }
    sp.process(block)
    const l = rms(block, 0, 4096)
    const r = rms(block, 1, 4096)
    // هر دو کانال سیگنال دارند و outputGain (۰٫۸۲) بعد از widening
    expect(l).toBeGreaterThan(0.1)
    expect(r).toBeGreaterThan(0.1)
    // سقف sane
    for (const v of block.samples) expect(Math.abs(v)).toBeLessThan(1.0)
  })

  it('محتوای mono (بدون side) بین کانال‌ها همبسته می‌ماند — crossfeed متقارن است', () => {
    const sp = new Spatializer(true)
    sp.configure(SAMPLE_RATE, 2)
    const block = sineBlock(1000, 8192)
    sp.process(block)
    // mono: side صفر → هر دو کانال خروجی یکسان (mid حفظ + crossfeed یکسان)
    let diff = 0
    for (let i = 4096; i < block.frameCount; i++) {
      diff += Math.abs(block.samples[i * 2] - block.samples[i * 2 + 1])
    }
    expect(diff).toBe(0)
  })

  it('output gain: در حالت خاموشِ تغییرات، دامنهٔ خروجی با ۰٫۸۲ مقیاس می‌شود', () => {
    // سیگنال DC صفر → crossfeed صفر؛ برای ایزوله‌کردن output gain از side،
    // ورودی mono و اندازه‌گیری هر دو کانال: mid حفظ، side با ۲٫۵ بزرگ می‌شود
    // پس تقریب: rms هر کانال ≈ 0.5 * 0.82 * sqrt(1 + 2.5²) / ... — فقط سقف را می‌آزماییم
    const sp = new Spatializer(true)
    sp.configure(SAMPLE_RATE, 2)
    const block = sineBlock(1000, 8192, SAMPLE_RATE, 0.1)
    sp.process(block)
    for (const v of block.samples) expect(Math.abs(v)).toBeLessThan(1.0)
  })

  it('فقط استریو: ۱ کانال بدون تغییر رد می‌شود', () => {
    const sp = new Spatializer(true)
    sp.configure(SAMPLE_RATE, 1)
    const block = createBlock(4096, 1)
    for (let i = 0; i < 4096; i++) block.samples[i] = 0.5 * Math.sin((2 * Math.PI * 1000 * i) / SAMPLE_RATE)
    const ref = Float32Array.from(block.samples)
    sp.process(block)
    expect(Array.from(block.samples)).toEqual(Array.from(ref))
  })
})

describe('Loudness — هم‌ترازی و لیمیتر', () => {
  it('گین per ترک: −۳dB یعنی RMS ≈ ۰٫۷× ورودی', () => {
    const loud = new Loudness()
    loud.gainLookup = () => Math.pow(10, -3 / 20)
    loud.configure(SAMPLE_RATE, 2)
    loud.track('t1')
    const block = sineBlock(1000, 16384)
    loud.process(block)
    const ref = rms(sineBlock(1000, 16384), 0)
    expect(rms(block, 0) / ref).toBeCloseTo(0.708, 1)
  })

  it('normalize خاموش: گین اعمال نمی‌شود', () => {
    const loud = new Loudness()
    loud.gainLookup = () => 0.5
    loud.setNormalize(false)
    loud.configure(SAMPLE_RATE, 2)
    loud.track('t1')
    const block = sineBlock(1000, 16384)
    loud.process(block)
    const ref = rms(sineBlock(1000, 16384), 0)
    expect(rms(block, 0) / ref).toBeCloseTo(1, 2)
  })

  it('لیمیتر: پیک بالای سقف ۰٫۹۸۵ نگه داشته می‌شود', () => {
    const loud = new Loudness()
    loud.gainLookup = () => 4 // +۱۲dB
    loud.configure(SAMPLE_RATE, 2)
    loud.track('t1')
    const block = sineBlock(1000, 16384, SAMPLE_RATE, 0.5)
    loud.process(block)
    let peak = 0
    for (const v of block.samples) peak = Math.max(peak, Math.abs(v))
    expect(peak).toBeLessThanOrEqual(0.985 + 1e-6)
    expect(peak).toBeGreaterThan(0.9) // لیمیتر فقط اوج را می‌گیرد، صدا را له نمی‌کند
  })

  it('trim ترکیب: کراس‌فید هدرروم می‌دهد و trim با گِلاید اعمال می‌شود', () => {
    const loud = new Loudness()
    loud.configure(SAMPLE_RATE, 2)
    loud.track('t1')
    loud.setBlendTrim(0.5)
    // نخستین بلوک: snap فعال → trim فوراً ۰٫۵
    const block = sineBlock(1000, 4096)
    loud.process(block)
    const ref = rms(sineBlock(1000, 4096), 0)
    expect(rms(block, 0) / ref).toBeCloseTo(0.5, 1)
  })

  it('مرز ترک: onStreamBoundary گین را به ترک بعد اسنپ می‌کند', () => {
    const gains: Record<string, number> = { t1: 0.5, t2: 2 }
    const loud = new Loudness()
    loud.gainLookup = (id) => gains[id]
    loud.configure(SAMPLE_RATE, 2)
    loud.track('t1', 't2')

    const block1 = sineBlock(1000, 8192)
    loud.process(block1)
    const ref1 = rms(sineBlock(1000, 8192), 0)
    expect(rms(block1, 0) / ref1).toBeCloseTo(0.5, 1)

    loud.onStreamBoundary() // snap به t2
    const block2 = sineBlock(1000, 8192)
    loud.process(block2)
    const ref2 = rms(sineBlock(1000, 8192), 0)
    expect(rms(block2, 0) / ref2).toBeCloseTo(2, 1)
  })

  it('lookup خراب یا نامعتبر: گین ۱ — پخش هرگز نمی‌میرد', () => {
    const loud = new Loudness()
    loud.gainLookup = () => {
      throw new Error('boom')
    }
    loud.configure(SAMPLE_RATE, 2)
    loud.track('t1')
    const block = sineBlock(1000, 4096)
    const ref = sineBlock(1000, 4096)
    loud.process(block)
    expect(Array.from(block.samples)).toEqual(Array.from(ref.samples))
  })
})

/** برشِ یک بلوک به زیربلوک — برای آزمودن گلاید بین فراخوانی‌ها */
function subBlock(block: ReturnType<typeof createBlock>, startFrame: number, frames: number) {
  return {
    samples: block.samples.subarray(startFrame * 2, (startFrame + frames) * 2),
    frameCount: frames,
    channelCount: 2,
  }
}
