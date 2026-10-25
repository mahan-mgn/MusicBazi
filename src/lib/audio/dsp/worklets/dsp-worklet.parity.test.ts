import { describe, expect, it } from 'vitest'
import workletCode from './dsp-worklet.js?raw'

import { Equalizer as TsEqualizer } from '../Equalizer'
import { Spatializer as TsSpatializer } from '../Spatializer'
import { Loudness as TsLoudness } from '../Loudness'
import { manualCurve } from '../EqCurve'
import type { DSPExposed } from './dsp-worklet.d'

/**
 * تست هم‌ارزی — تضمین مکانیکی اینکه کپی JS داخل پوستهٔ ورک‌لت (`dsp-worklet.js`)
 * با کلاس‌های خالص TypeScript بیت‌به‌بیت یکی خروجی می‌دهد.
 *
 * اگر یکی از دو نسخه عوض شود و دیگری نه، همین تست قرمز می‌شود و دو نسخه
 * از هم فاصله نمی‌گیرند.
 */

/** اجرای فایل ورک‌لت در Node و بیرون‌کشی کلاس‌های خالص آن */
function loadWorkletDSP(): DSPExposed {
  let exposed: DSPExposed | null = null
  // پارامتر `globalThis` سایهٔ global واقعی داخل بدنهٔ فایل است — قلاب تست
  // همان‌جا می‌نشیند و کلاس‌ها بیرون می‌آیند
  const fn = new Function('globalThis', workletCode)
  fn({ __dspWorkletTestHook: (dsp: DSPExposed) => { exposed = dsp } })
  if (!exposed) throw new Error('dsp-worklet.js test hook did not fire')
  return exposed
}

const SAMPLE_RATE = 48_000

function sineStereo(freq: number, frames: number, amplitude = 0.4, phase = 0): Float32Array {
  const samples = new Float32Array(frames * 2)
  for (let i = 0; i < frames; i++) {
    const v = amplitude * Math.sin((2 * Math.PI * freq * i) / SAMPLE_RATE + phase)
    samples[i * 2] = v
    samples[i * 2 + 1] = v
  }
  return samples
}

function maxAbsDiff(a: Float32Array, b: Float32Array): number {
  let max = 0
  for (let i = 0; i < a.length; i++) {
    max = Math.max(max, Math.abs(a[i] - b[i]))
  }
  return max
}

describe('هم‌ارزی پوستهٔ ورک‌لت با کلاس‌های TypeScript', () => {
  it('Equalizer: خروجی بیت‌به‌بیت یکسان روی سیگنال واقعی', () => {
    const dsp = loadWorkletDSP()
    const curve = manualCurve([3, -2, 0, 6, 1.5, -1, 4])

    const ts = new TsEqualizer()
    ts.configure(SAMPLE_RATE, 2)
    ts.setTarget({ enabled: true, curve, balance: 0.25 })

    const js = new dsp.Equalizer()
    js.configure(SAMPLE_RATE, 2)
    js.setTarget(curve, 0.25, true)

    // سه بلوک — تا گذارِ گلاید هم پوشش داده شود
    let tsSamples = new Float32Array(0)
    let jsSamples = new Float32Array(0)
    for (let b = 0; b < 3; b++) {
      const signal = sineStereo(400 + b * 700, 2048)
      const tsBlock = { samples: Float32Array.from(signal), frameCount: 2048, channelCount: 2 }
      const jsSamples2 = Float32Array.from(signal)
      ts.process(tsBlock)
      js.process(jsSamples2, 2048, 2)
      tsSamples = Float32Array.from([...tsSamples, ...tsBlock.samples])
      jsSamples = Float32Array.from([...jsSamples, ...jsSamples2])
    }

    expect(maxAbsDiff(tsSamples, jsSamples)).toBeLessThan(1e-9)
  })

  it('Spatializer: خروجی بیت‌به‌بیت یکسان', () => {
    const dsp = loadWorkletDSP()
    const ts = new TsSpatializer(true)
    ts.configure(SAMPLE_RATE, 2)
    const js = new dsp.Spatializer(true)
    js.configure(SAMPLE_RATE, 2)

    const signal = new Float32Array(4096 * 2)
    for (let i = 0; i < 4096; i++) {
      signal[i * 2] = 0.3 * Math.sin((2 * Math.PI * 700 * i) / SAMPLE_RATE)
      signal[i * 2 + 1] = 0.3 * Math.sin((2 * Math.PI * 700 * i) / SAMPLE_RATE + 1.1)
    }
    const tsBlock = { samples: Float32Array.from(signal), frameCount: 4096, channelCount: 2 }
    const jsSamples = Float32Array.from(signal)
    ts.process(tsBlock)
    js.process(jsSamples, 4096, 2)

    expect(maxAbsDiff(tsBlock.samples, jsSamples)).toBeLessThan(1e-9)
  })

  it('Loudness: گین، لیمیتر و trim — خروجی بیت‌به‌بیت یکسان', () => {
    const dsp = loadWorkletDSP()
    const ts = new TsLoudness()
    ts.gainLookup = (id) => (id === 't1' ? Math.pow(10, -2 / 20) : 1)
    ts.configure(SAMPLE_RATE, 2)
    ts.track('t1')
    ts.setBlendTrim(0.8)

    const js = new dsp.Loudness()
    js.gainByMediaId['t1'] = Math.pow(10, -2 / 20)
    js.configure(SAMPLE_RATE, 2)
    js.track('t1')
    js.setBlendTrim(0.8)

    const tsBlock = { samples: sineStereo(1000, 4096, 0.6), frameCount: 4096, channelCount: 2 }
    const jsSamples = sineStereo(1000, 4096, 0.6)
    ts.process(tsBlock)
    js.process(jsSamples, 4096, 2)

    expect(maxAbsDiff(tsBlock.samples, jsSamples)).toBeLessThan(1e-9)
  })

  it('فایل ورک‌لت import ندارد — افزودن import همان لحظه addModule را در ساخت می‌شکند', () => {
    expect(workletCode).not.toMatch(/^\s*import\s/m)
    expect(workletCode).toContain("registerProcessor('mb-equalizer'")
    expect(workletCode).toContain("registerProcessor('mb-spatial'")
    expect(workletCode).toContain("registerProcessor('mb-loudness'")
  })
})
