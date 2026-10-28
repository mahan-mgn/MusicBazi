/*
 * پورت `dsp/EqualizerProcessor.kt` اندروید — اکولایزر پارامتریک ۱۰ سکشن
 * (۷ باند دستی + ۳ اسلات پد تون) با preamp و balance.
 *
 * پیاده‌سازی: سکشن‌های state-variable دومرحله‌ای با تبدیل دوسویی
 * (bilinear) و pre-warp فرکانس — همان «trapezoidal SVF».
 *
 * Copyright (C) 2024-2026 Kushagra Singh / BitChord Contributors, GPL-3.0
 * (پورت‌شده به Music Bazi — همین پرونده هم تحت GPL-3.0 منتشر می‌شود)
 */

import { EQ_SLOTS, SLOTS, type EqCurve, type FilterSlot } from './EqCurve'

/** تیونینگِ هدف — همیشه یک‌جا عوض می‌شود، هرگز در جا ویرایش نمی‌شود */
interface Tuning {
  curve: EqCurve
  balance: number
}

const OFF_TUNING: Tuning = { curve: FLAT_CACHE(), balance: 0 }

function FLAT_CACHE(): EqCurve {
  return { gainsDb: new Float32Array(SLOTS), qs: new Float32Array(SLOTS).fill(0.707), preampDb: 0 }
}

// ثابت‌های پردازش — دقیقاً همان companion object کاتلین
const GLIDE_FRAMES = 64
const GLIDE_RATE = 0.08
const SETTLED_DB = 0.01
const SETTLED_BALANCE = 0.0005
const MIN_Q = 0.05
const MIN_HZ = 10
const MAX_FREQUENCY_FRACTION = 0.45
const DENORMAL_FLOOR = 1e-12

export interface EqualizerTarget {
  enabled: boolean
  curve: EqCurve
  /** −۱ (تمام چپ) تا +۱ (تمام راست) */
  balance: number
}

/**
 * اکولایزر SVF — کلاس خالص، بدون وابستگی به مرورگر.
 *
 * استفاده: `configure(sampleRate, channels)` یک‌بار، بعد `process(block)`
 * روی هر بلوک. تغییر تیونینگ حین پخش آزاد است (`setTarget`) — ضرایب با
 * گِلاید نرم دنبالش می‌روند و صدای تقه نمی‌دهد.
 */
export class Equalizer {
  private target: Tuning = OFF_TUNING

  private sampleRate = 0
  private channelCount = 0

  private currentGainDb = new Float32Array(SLOTS)
  private currentQ = new Float32Array(SLOTS).fill(0.707)
  private currentPreampDb = 0
  private currentBalance = 0

  private coeffA1 = new Float32Array(SLOTS)
  private coeffA2 = new Float32Array(SLOTS)
  private coeffA3 = new Float32Array(SLOTS)
  private mixInput = new Float32Array(SLOTS)
  private mixBand = new Float32Array(SLOTS)
  private mixLow = new Float32Array(SLOTS)

  /** کدام سکشن‌ها در این زیربلوک ارزش اجرا دارند و چندتا */
  private activeSlots = new Int32Array(SLOTS)
  private running = new Uint8Array(SLOTS)

  /** دو حالت انتگرال‌گیر per سکشن، per کانال */
  private state = new Float32Array(0)

  /** گِین خروجی per کانال: preamp جبرانی + balance استریو */
  private channelGain = new Float32Array(0)

  setTarget(target: EqualizerTarget): void {
    this.target = target.enabled
      ? { curve: target.curve, balance: clamp(target.balance, -1, 1) }
      : OFF_TUNING
  }

  get isEnabled(): boolean {
    return this.target !== OFF_TUNING
  }

  configure(sampleRate: number, channelCount: number): void {
    this.sampleRate = sampleRate
    this.channelCount = channelCount
    const requiredSize = channelCount * SLOTS * 2
    if (this.state.length !== requiredSize) {
      this.state = new Float32Array(requiredSize)
    }
    if (this.channelGain.length !== channelCount) {
      this.channelGain = new Float32Array(channelCount).fill(1)
    }
    this.running.fill(0)
    this.snapToTarget()
  }

  /** پردازش در جا روی بلوک interleaved Float32 — headroom حفظ می‌شود */
  process(block: { samples: Float32Array; frameCount: number; channelCount: number }): void {
    const frameCount = block.frameCount
    if (frameCount === 0 || this.channelCount < 1 || this.sampleRate <= 0) return

    const tuning = this.target
    if (isFlat(tuning) && this.isSettled(tuning)) return

    let remaining = frameCount
    let frameOffset = 0
    while (remaining > 0) {
      const subBlock = Math.min(remaining, GLIDE_FRAMES)
      this.glideTowards(tuning)
      const active = this.prepareSections()
      this.prepareChannelGains()

      for (let f = 0; f < subBlock; f++) {
        const baseIdx = (frameOffset + f) * this.channelCount
        for (let channel = 0; channel < this.channelCount; channel++) {
          let sample = block.samples[baseIdx + channel]
          for (let index = 0; index < active; index++) {
            sample = this.section(this.activeSlots[index], channel, sample)
          }
          block.samples[baseIdx + channel] = sample * this.channelGain[channel]
        }
      }
      this.flushDenormals(active)
      frameOffset += subBlock
      remaining -= subBlock
    }
  }

  /** ریست کامل حالت — پرش ترک، flush ورک‌لت */
  reset(): void {
    this.state.fill(0)
    this.running.fill(0)
    this.snapToTarget()
  }

  // ---- گلاید ------------------------------------------------------------

  private snapToTarget(): void {
    const tuning = this.target
    this.currentGainDb.set(tuning.curve.gainsDb)
    this.currentQ.set(tuning.curve.qs)
    this.currentPreampDb = tuning.curve.preampDb
    this.currentBalance = tuning.balance
  }

  private glideTowards(tuning: Tuning): void {
    for (let slot = 0; slot < SLOTS; slot++) {
      this.currentGainDb[slot] = linearGlide(this.currentGainDb[slot], tuning.curve.gainsDb[slot])
      this.currentQ[slot] = geometricGlide(this.currentQ[slot], tuning.curve.qs[slot])
    }
    this.currentPreampDb = linearGlide(this.currentPreampDb, tuning.curve.preampDb)
    this.currentBalance = linearGlide(this.currentBalance, tuning.balance)
  }

  private prepareSections(): number {
    let active = 0
    for (let slot = 0; slot < SLOTS; slot++) {
      if (Math.abs(this.currentGainDb[slot]) >= SETTLED_DB) {
        this.updateCoefficients(slot)
        this.activeSlots[active++] = slot
        this.running[slot] = 1
      } else if (this.running[slot]) {
        this.clearState(slot)
        this.running[slot] = 0
      }
    }
    return active
  }

  private updateCoefficients(slot: number): void {
    if (this.sampleRate <= 0) return
    const spec: FilterSlot = EQ_SLOTS[slot]
    const a = Math.pow(10, this.currentGainDb[slot] / 40)
    const q = Math.max(MIN_Q, this.currentQ[slot])
    const base = Math.tan((Math.PI * usableFrequency(spec.frequencyHz, this.sampleRate)) / this.sampleRate)
    let g: number
    let k: number
    switch (spec.kind) {
      case 'BELL':
        g = base
        k = 1 / (q * a)
        this.mixInput[slot] = 1
        this.mixBand[slot] = k * (a * a - 1)
        this.mixLow[slot] = 0
        break
      case 'LOW_SHELF':
        g = base / Math.sqrt(a)
        k = 1 / q
        this.mixInput[slot] = 1
        this.mixBand[slot] = k * (a - 1)
        this.mixLow[slot] = a * a - 1
        break
      case 'HIGH_SHELF':
        g = base * Math.sqrt(a)
        k = 1 / q
        this.mixInput[slot] = a * a
        this.mixBand[slot] = k * (1 - a) * a
        this.mixLow[slot] = 1 - a * a
        break
    }
    const d = 1 / (1 + g * (g + k))
    this.coeffA1[slot] = d
    this.coeffA2[slot] = g * d
    this.coeffA3[slot] = g * (g * d)
  }

  private isSettled(tuning: Tuning): boolean {
    if (Math.abs(this.currentBalance - tuning.balance) >= SETTLED_BALANCE) return false
    if (Math.abs(this.currentPreampDb - tuning.curve.preampDb) >= SETTLED_DB) return false
    for (let slot = 0; slot < SLOTS; slot++) {
      if (Math.abs(this.currentGainDb[slot] - tuning.curve.gainsDb[slot]) >= SETTLED_DB) return false
    }
    return true
  }

  private prepareChannelGains(): void {
    const preamp = Math.pow(10, this.currentPreampDb / 20)
    if (this.channelCount === 2) {
      this.channelGain[0] = preamp * Math.min(1, 1 - this.currentBalance)
      this.channelGain[1] = preamp * Math.min(1, 1 + this.currentBalance)
    } else {
      this.channelGain.fill(preamp)
    }
  }

  // ---- فیلتر ------------------------------------------------------------

  private section(slot: number, channel: number, input: number): number {
    const i = (channel * SLOTS + slot) * 2
    const ic1 = this.state[i]
    const ic2 = this.state[i + 1]
    const v3 = input - ic2
    const v1 = this.coeffA1[slot] * ic1 + this.coeffA2[slot] * v3
    const v2 = ic2 + this.coeffA2[slot] * ic1 + this.coeffA3[slot] * v3
    this.state[i] = 2 * v1 - ic1
    this.state[i + 1] = 2 * v2 - ic2
    return this.mixInput[slot] * input + this.mixBand[slot] * v1 + this.mixLow[slot] * v2
  }

  private clearState(slot: number): void {
    for (let channel = 0; channel < this.channelCount; channel++) {
      const i = (channel * SLOTS + slot) * 2
      this.state[i] = 0
      this.state[i + 1] = 0
    }
  }

  private flushDenormals(active: number): void {
    for (let index = 0; index < active; index++) {
      const slot = this.activeSlots[index]
      for (let channel = 0; channel < this.channelCount; channel++) {
        const i = (channel * SLOTS + slot) * 2
        if (Math.abs(this.state[i]) < DENORMAL_FLOOR) this.state[i] = 0
        if (Math.abs(this.state[i + 1]) < DENORMAL_FLOOR) this.state[i + 1] = 0
      }
    }
  }
}

function linearGlide(current: number, target: number): number {
  return current + (target - current) * GLIDE_RATE
}

function geometricGlide(current: number, target: number): number {
  const from = Math.log(Math.max(MIN_Q, current))
  const to = Math.log(Math.max(MIN_Q, target))
  return Math.exp(from + (to - from) * GLIDE_RATE)
}

function isFlat(tuning: Tuning): boolean {
  if (Math.abs(tuning.balance) >= SETTLED_BALANCE) return false
  if (Math.abs(tuning.curve.preampDb) >= SETTLED_DB) return false
  for (let slot = 0; slot < SLOTS; slot++) {
    if (Math.abs(tuning.curve.gainsDb[slot]) >= SETTLED_DB) return false
  }
  return true
}

function usableFrequency(hz: number, sampleRate: number): number {
  return clamp(hz, MIN_HZ, sampleRate * MAX_FREQUENCY_FRACTION)
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}
