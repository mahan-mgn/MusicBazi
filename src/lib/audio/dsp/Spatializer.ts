/*
 * پورت `dsp/SpatialAudioProcessor.kt` اندروید — عریض‌کنندهٔ استریو mid/side
 * با crossfeed تأخیری و فیلتر پایین‌گذر.
 *
 * Copyright (C) 2024-2026 Kushagra Singh / BitChord Contributors, GPL-3.0
 * (پورت‌شده به Music Bazi — همین پرونده هم تحت GPL-3.0 منتشر می‌شود)
 */

// ثابت‌های پردازش — همان کاتلین
const WIDTH_GAIN = 2.5
const OUTPUT_GAIN = 0.82
const CROSSFEED_GAIN = 0.2
const LOWPASS_COEFF = 0.3
const DELAY_MS = 15

/**
 * کلاس خالص — فقط استریو (۲ کانال) پردازش می‌کند؛ بقیهٔ چیدمان‌ها بدون تغییر
 * رد می‌شوند (همان رفتار `if (block.channelCount != 2) return` اندروید).
 */
export class Spatializer {
  private sampleRate = 0
  private channelCount = 0

  private delayLeft = new Float32Array(0)
  private delayRight = new Float32Array(0)
  private delayIndex = 0
  private lowpassLeft = 0
  private lowpassRight = 0

  constructor(public enabled = false) {}

  configure(sampleRate: number, channelCount: number): void {
    this.sampleRate = sampleRate
    this.channelCount = channelCount
    if (channelCount !== 2 || sampleRate <= 0) {
      this.delayLeft = new Float32Array(0)
      this.delayRight = new Float32Array(0)
      this.delayIndex = 0
      this.lowpassLeft = 0
      this.lowpassRight = 0
      return
    }
    const delaySamples = Math.max(1, Math.round((sampleRate * DELAY_MS) / 1000))
    if (this.delayLeft.length !== delaySamples) {
      this.delayLeft = new Float32Array(delaySamples)
      this.delayRight = new Float32Array(delaySamples)
    }
    this.flush()
  }

  process(block: { samples: Float32Array; frameCount: number; channelCount: number }): void {
    if (!this.enabled || block.frameCount === 0) return
    if (block.channelCount !== 2) return

    const delaySize = this.delayLeft.length
    if (delaySize === 0) return

    const totalSamples = block.frameCount * 2
    let idx = 0
    let dIdx = this.delayIndex
    let lpL = this.lowpassLeft
    let lpR = this.lowpassRight

    while (idx < totalSamples) {
      const left = block.samples[idx]
      const right = block.samples[idx + 1]

      const mid = (left + right) * 0.5
      const side = (left - right) * 0.5 * WIDTH_GAIN
      const widenedLeft = mid + side
      const widenedRight = mid - side

      const delayedRight = this.delayRight[dIdx]
      const delayedLeft = this.delayLeft[dIdx]
      lpL += LOWPASS_COEFF * (delayedRight - lpL)
      lpR += LOWPASS_COEFF * (delayedLeft - lpR)
      block.samples[idx] = (widenedLeft + lpL * CROSSFEED_GAIN) * OUTPUT_GAIN
      block.samples[idx + 1] = (widenedRight + lpR * CROSSFEED_GAIN) * OUTPUT_GAIN

      this.delayLeft[dIdx] = left
      this.delayRight[dIdx] = right
      dIdx = (dIdx + 1) % delaySize
      idx += 2
    }

    this.delayIndex = dIdx
    this.lowpassLeft = lpL
    this.lowpassRight = lpR
  }

  flush(): void {
    this.delayLeft.fill(0)
    this.delayRight.fill(0)
    this.delayIndex = 0
    this.lowpassLeft = 0
    this.lowpassRight = 0
  }

  reset(): void {
    this.flush()
  }

  /** فقط برای تست/دیاگ */
  get isConfigured(): boolean {
    return this.channelCount === 2 && this.delayLeft.length > 0 && this.sampleRate > 0
  }
}
