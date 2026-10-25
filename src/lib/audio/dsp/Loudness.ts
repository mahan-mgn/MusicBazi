/*
 * پورت `dsp/LoudnessProcessor.kt` اندروید — هم‌ترازی بلندی per ترک + لیمیتر
 * پیک که نتیجه (و کراس‌فیدی که روی آن سوار است) را از کلیپ نگه می‌دارد.
 *
 * Copyright (C) 2024-2026 Kushagra Singh / BitChord Contributors, GPL-3.0
 * (پورت‌شده به Music Bazi — همین پرونده هم تحت GPL-3.0 منتشر می‌شود)
 */

// ثابت‌های پردازش — همان companion کاتلین
const LIMIT = 0.985
const MIN_TRIM = 0.5
const GLIDE_SECONDS = 0.04
const RELEASE_SECONDS = 0.08
const SETTLED = 1e-4

/**
 * کلاس خالص.
 *
 * گِینِ هر ترک از `gainLookup` می‌آید (سرور عدد EBU R128 را می‌دهد). مرزِ
 * ترک (`onStreamBoundary`) گِین را بدون گِلاید به ترک بعدی می‌بَرد تا
 * سوییچِ گپلس تیک ندهد. trim حین کراس‌فید از هدررومِ ترکیب می‌آید.
 */
export class Loudness {
  /** گِین خطی برای شناسهٔ ترک: ۱ وقتی نامعلوم یا هم‌ترازی خاموش است */
  gainLookup: (mediaId: string) => number = () => 1

  private mediaId: string | null = null
  private nextMediaId: string | null = null

  private trimTarget = 1
  private normalize = true

  private sampleRate = 0
  private channelCount = 0
  private currentGain = 1
  private currentTrim = 1
  private reduction = 1
  private glideCoef = 1
  private releaseCoef = 1
  private snap = true

  /** این زنجیره روی کدام ترک (و ترک بعدیِ گپلسِ همان دک) نشسته */
  track(mediaId: string | null, nextMediaId: string | null = null): void {
    this.mediaId = mediaId
    this.nextMediaId = nextMediaId
  }

  setNormalize(on: boolean): void {
    this.normalize = on
  }

  /** هدررومِ ترکیب حین کراس‌فید — روی thread صدا گِلاید می‌شود */
  setBlendTrim(value: number): void {
    this.trimTarget = Math.max(MIN_TRIM, Math.min(1, value))
  }

  /** مرز ترک — گِین به ترک بعدی اسنپ می‌شود */
  onStreamBoundary(): void {
    if (this.nextMediaId !== null) this.mediaId = this.nextMediaId
    this.snap = true
  }

  configure(sampleRate: number, channelCount: number): void {
    this.sampleRate = sampleRate
    this.channelCount = channelCount
    this.glideCoef = coefficient(GLIDE_SECONDS, sampleRate)
    this.releaseCoef = coefficient(RELEASE_SECONDS, sampleRate)
    this.snap = true
  }

  flush(): void {
    this.reduction = 1
    this.snap = true
  }

  reset(): void {
    this.sampleRate = 0
    this.channelCount = 0
    this.reduction = 1
    this.snap = true
  }

  /** گِین هدف: فقط هم‌ترازی per ترک — تقویت سراسری (boost) روی GainNode مستر گراف است */
  private targetGain(): number {
    return this.mediaId !== null && this.normalize ? safeGain(this.gainLookup, this.mediaId) : 1
  }

  process(block: { samples: Float32Array; frameCount: number; channelCount: number }): void {
    const frames = block.frameCount
    const channels = this.channelCount
    if (frames === 0 || channels < 1 || this.sampleRate <= 0) return

    const targetGain = this.targetGain()
    const targetTrim = this.trimTarget
    if (this.snap) {
      this.currentGain = targetGain
      this.currentTrim = targetTrim
      this.snap = false
    }

    if (
      targetGain === 1 &&
      targetTrim >= 1 &&
      Math.abs(this.currentGain - 1) < SETTLED &&
      this.currentTrim >= 1 - SETTLED &&
      this.reduction >= 1 - SETTLED
    ) {
      this.currentGain = 1
      this.currentTrim = 1
      this.reduction = 1
      return
    }

    const samples = block.samples
    let gain = this.currentGain
    let trim = this.currentTrim
    let gr = this.reduction
    let index = 0
    for (let frame = 0; frame < frames; frame++) {
      gain += (targetGain - gain) * this.glideCoef
      trim += (targetTrim - trim) * this.glideCoef
      const scale = gain * trim
      let peak = 0
      for (let channel = 0; channel < channels; channel++) {
        const magnitude = Math.abs(samples[index + channel])
        if (magnitude > peak) peak = magnitude
      }
      peak *= scale
      const wanted = peak > LIMIT ? LIMIT / peak : 1
      gr = wanted < gr ? wanted : gr + (wanted - gr) * this.releaseCoef
      const applied = scale * gr
      for (let channel = 0; channel < channels; channel++) {
        samples[index + channel] *= applied
      }
      index += channels
    }
    this.currentGain = gain
    this.currentTrim = trim
    this.reduction = gr
  }
}

function safeGain(lookup: (id: string) => number, id: string): number {
  try {
    const gain = lookup(id)
    return Number.isFinite(gain) && gain > 0 ? gain : 1
  } catch {
    return 1
  }
}

function coefficient(seconds: number, rate: number): number {
  return rate <= 0 ? 1 : 1 - Math.exp(-1 / (seconds * rate))
}
