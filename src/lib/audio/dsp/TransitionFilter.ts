/*
 * پورت `dsp/TransitionFilterProcessor.kt` اندروید — فیلتر ترنزیشن و رینگ‌بافر اکو
 *
 * Copyright (C) 2024-2026 Kushagra Singh / BitChord Contributors, GPL-3.0
 * (پورت‌شده به Music Bazi — همین پرونده هم تحت GPL-3.0 منتشر می‌شود)
 */

export const OPEN_HZ = 20_000
export const OFF_HZ = 20
export const MAX_HIGH_PASS_HZ = 2_000
const MIN_HZ = 10
const STAGES = 2
const BUTTERWORTH_Q = [0.54120, 1.30656]
const GLIDE_FRAMES = 64
const GLIDE_RATE = 0.05
const SETTLED_HZ = 1
const MAX_CUTOFF_FRACTION = 0.45
const ECHO_FEEDBACK = 0.4
const ECHO_WET = 0.5
const ECHO_LOW_PASS_HZ = 3_500
const ECHO_HIGH_PASS_HZ = 250
const MAX_ECHO_SECONDS = 1.0

function onePole(hz: number, sampleRate: number): number {
  if (sampleRate <= 0) return 0
  return 1 - Math.exp((-2 * Math.PI * hz) / sampleRate)
}

function clamp(v: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, v))
}

export class TransitionFilter {
  targetLowPassHz = OPEN_HZ
  targetHighPassHz = OFF_HZ

  private channelCount = 0
  private sampleRate = 0

  private currentLowPassHz = OPEN_HZ
  private currentHighPassHz = OFF_HZ

  private lowState = new Float32Array(0)
  private highState = new Float32Array(0)

  private lowA1 = new Float32Array(STAGES)
  private lowA2 = new Float32Array(STAGES)
  private lowA3 = new Float32Array(STAGES)
  private highA1 = new Float32Array(STAGES)
  private highA2 = new Float32Array(STAGES)
  private highA3 = new Float32Array(STAGES)
  private highK = new Float32Array(STAGES)

  private filterStateDirty = false

  private echoEngaged = false
  private echoTargetSend = 0
  private echoTargetDry = 1
  private echoSeconds = 0

  private echoGeneration = 0
  private pendingEchoRing: Float32Array<ArrayBuffer> | null = null

  private echoFormatRate = 0
  private echoFormatChannels = 0

  private echoRing: Float32Array<ArrayBuffer> = new Float32Array(0)
  private echoSeenGeneration = 0
  private echoDelayFrames = 0
  private echoPosition = 0
  private echoSend = 0
  private echoDry = 1
  private echoLow = new Float32Array(0)
  private echoHigh = new Float32Array(0)
  private echoLowCoefficient = 0
  private echoHighCoefficient = 0

  setCutoffs(lowPassHz: number, highPassHz: number): void {
    this.targetLowPassHz = clamp(lowPassHz, MIN_HZ, OPEN_HZ)
    this.targetHighPassHz = clamp(highPassHz, OFF_HZ, MAX_HIGH_PASS_HZ)
  }

  open(): void {
    this.setCutoffs(OPEN_HZ, OFF_HZ)
  }

  get isFiltering(): boolean {
    return (
      this.targetLowPassHz < OPEN_HZ ||
      this.targetHighPassHz > OFF_HZ ||
      this.currentLowPassHz < OPEN_HZ - SETTLED_HZ ||
      this.currentHighPassHz > OFF_HZ + SETTLED_HZ
    )
  }

  setEcho(delaySeconds: number, send: number, dry: number): void {
    if (delaySeconds !== this.echoSeconds || !this.echoEngaged) {
      const frames = Math.floor(clamp(delaySeconds, 0, MAX_ECHO_SECONDS) * this.echoFormatRate)
      const needed = frames * this.echoFormatChannels
      if (needed > this.echoRing.length) {
        this.pendingEchoRing = new Float32Array(needed)
      }
      this.echoSeconds = delaySeconds
      this.echoGeneration++
    }
    this.echoTargetSend = clamp(send, 0, 1)
    this.echoTargetDry = clamp(dry, 0, 1)
    this.echoEngaged = true
  }

  parkEcho(): void {
    this.echoEngaged = false
    this.echoTargetSend = 0
    this.echoTargetDry = 1
  }

  configure(sampleRate: number, channelCount: number): void {
    this.sampleRate = sampleRate
    this.channelCount = channelCount
    const requiredSize = channelCount * STAGES * 2
    if (this.lowState.length !== requiredSize) {
      this.lowState = new Float32Array(requiredSize)
      this.highState = new Float32Array(requiredSize)
    }
    this.currentLowPassHz = this.targetLowPassHz
    this.currentHighPassHz = this.targetHighPassHz
    if (this.echoLow.length !== channelCount) {
      this.echoLow = new Float32Array(channelCount)
      this.echoHigh = new Float32Array(channelCount)
    }
    this.echoLowCoefficient = onePole(ECHO_LOW_PASS_HZ, sampleRate)
    this.echoHighCoefficient = onePole(ECHO_HIGH_PASS_HZ, sampleRate)
    this.echoFormatRate = sampleRate
    this.echoFormatChannels = channelCount
    this.echoSeenGeneration = this.echoGeneration - 1
  }

  process(block: { samples: Float32Array; frameCount: number; channelCount: number }): void {
    const frameCount = block.frameCount
    if (frameCount === 0 || this.channelCount < 1 || this.sampleRate <= 0) return
    this.filter(block, frameCount)
    if (this.echoEngaged) this.echo(block, frameCount)
  }

  private filter(block: { samples: Float32Array; frameCount: number; channelCount: number }, frameCount: number): void {
    const targetLow = this.targetLowPassHz
    const targetHigh = this.targetHighPassHz
    const parked =
      targetLow >= OPEN_HZ &&
      targetHigh <= OFF_HZ &&
      this.currentLowPassHz >= OPEN_HZ - SETTLED_HZ &&
      this.currentHighPassHz <= OFF_HZ + SETTLED_HZ

    if (parked) {
      this.clearStateIfNeeded()
      return
    }
    this.filterStateDirty = true

    let remaining = frameCount
    let frameOffset = 0
    while (remaining > 0) {
      const subBlock = Math.min(remaining, GLIDE_FRAMES)
      this.currentLowPassHz = this.glide(this.currentLowPassHz, targetLow)
      this.currentHighPassHz = this.glide(this.currentHighPassHz, targetHigh)
      const lowOn = this.currentLowPassHz < OPEN_HZ - SETTLED_HZ
      const highOn = this.currentHighPassHz > OFF_HZ + SETTLED_HZ
      if (lowOn) this.updateLowCoefficients()
      if (highOn) this.updateHighCoefficients()

      for (let f = 0; f < subBlock; f++) {
        const baseIdx = (frameOffset + f) * this.channelCount
        for (let channel = 0; channel < this.channelCount; channel++) {
          let sample = block.samples[baseIdx + channel]
          if (lowOn) sample = this.lowPass(channel, sample)
          if (highOn) sample = this.highPass(channel, sample)
          block.samples[baseIdx + channel] = sample
        }
      }
      frameOffset += subBlock
      remaining -= subBlock
    }
  }

  private clearStateIfNeeded(): void {
    if (!this.filterStateDirty) return
    this.lowState.fill(0)
    this.highState.fill(0)
    this.filterStateDirty = false
  }

  private echo(block: { samples: Float32Array; frameCount: number; channelCount: number }, frameCount: number): void {
    if (this.echoSeenGeneration !== this.echoGeneration) this.startEcho()
    const channels = this.channelCount
    const delay = this.echoDelayFrames
    const ring = this.echoRing
    const samples = block.samples
    const targetSend = this.echoTargetSend
    const targetDry = this.echoTargetDry
    const sendStep = (targetSend - this.echoSend) / frameCount
    const dryStep = (targetDry - this.echoDry) / frameCount
    let send = this.echoSend
    let dry = this.echoDry

    if (delay <= 0) {
      for (let f = 0; f < frameCount; f++) {
        dry += dryStep
        const base = f * channels
        for (let c = 0; c < channels; c++) samples[base + c] *= dry
      }
      this.echoSend = targetSend
      this.echoDry = targetDry
      return
    }

    const lowCoefficient = this.echoLowCoefficient
    const highCoefficient = this.echoHighCoefficient
    const low = this.echoLow
    const high = this.echoHigh
    let position = this.echoPosition

    for (let f = 0; f < frameCount; f++) {
      send += sendStep
      dry += dryStep
      const base = f * channels
      const ringBase = position * channels
      for (let c = 0; c < channels; c++) {
        const input = samples[base + c]
        const delayed = ring[ringBase + c]
        const darker = low[c] + lowCoefficient * (delayed - low[c])
        low[c] = darker
        const rumble = high[c] + highCoefficient * (darker - high[c])
        high[c] = rumble
        ring[ringBase + c] = input * send + (darker - rumble) * ECHO_FEEDBACK
        samples[base + c] = input * dry + delayed * ECHO_WET
      }
      if (++position === delay) position = 0
    }
    this.echoPosition = position
    this.echoSend = targetSend
    this.echoDry = targetDry
  }

  private startEcho(): void {
    this.echoSeenGeneration = this.echoGeneration
    if (this.pendingEchoRing) {
      this.echoRing = this.pendingEchoRing
      this.pendingEchoRing = null
    }
    const channels = Math.max(1, this.channelCount)
    this.echoDelayFrames = clamp(
      Math.floor(this.echoSeconds * this.sampleRate),
      0,
      Math.floor(this.echoRing.length / channels),
    )
    this.echoRing.fill(0, 0, this.echoDelayFrames * channels)
    this.echoLow.fill(0)
    this.echoHigh.fill(0)
    this.echoPosition = 0
    this.echoSend = 0
    this.echoDry = 1
  }

  private glide(current: number, target: number): number {
    const from = Math.log(Math.max(current, MIN_HZ))
    const to = Math.log(Math.max(target, MIN_HZ))
    return Math.exp(from + (to - from) * GLIDE_RATE)
  }

  private usableCutoff(hz: number): number {
    return clamp(hz, MIN_HZ, this.sampleRate * MAX_CUTOFF_FRACTION)
  }

  private updateLowCoefficients(): void {
    if (this.sampleRate <= 0) return
    const g = Math.tan((Math.PI * this.usableCutoff(this.currentLowPassHz)) / this.sampleRate)
    for (let stage = 0; stage < STAGES; stage++) {
      const k = 1 / BUTTERWORTH_Q[stage]
      const a1 = 1 / (1 + g * (g + k))
      this.lowA1[stage] = a1
      this.lowA2[stage] = g * a1
      this.lowA3[stage] = g * (g * a1)
    }
  }

  private updateHighCoefficients(): void {
    if (this.sampleRate <= 0) return
    const g = Math.tan((Math.PI * this.usableCutoff(this.currentHighPassHz)) / this.sampleRate)
    for (let stage = 0; stage < STAGES; stage++) {
      const k = 1 / BUTTERWORTH_Q[stage]
      const a1 = 1 / (1 + g * (g + k))
      this.highA1[stage] = a1
      this.highA2[stage] = g * a1
      this.highA3[stage] = g * (g * a1)
      this.highK[stage] = k
    }
  }

  private lowPass(channel: number, input: number): number {
    let value = input
    for (let stage = 0; stage < STAGES; stage++) {
      const i = (channel * STAGES + stage) * 2
      const ic1 = this.lowState[i]
      const ic2 = this.lowState[i + 1]
      const v3 = value - ic2
      const v1 = this.lowA1[stage] * ic1 + this.lowA2[stage] * v3
      const v2 = ic2 + this.lowA2[stage] * ic1 + this.lowA3[stage] * v3
      this.lowState[i] = 2 * v1 - ic1
      this.lowState[i + 1] = 2 * v2 - ic2
      value = v2
    }
    return value
  }

  private highPass(channel: number, input: number): number {
    let value = input
    for (let stage = 0; stage < STAGES; stage++) {
      const i = (channel * STAGES + stage) * 2
      const ic1 = this.highState[i]
      const ic2 = this.highState[i + 1]
      const v3 = value - ic2
      const v1 = this.highA1[stage] * ic1 + this.highA2[stage] * v3
      const v2 = ic2 + this.highA2[stage] * ic1 + this.highA3[stage] * v3
      this.highState[i] = 2 * v1 - ic1
      this.highState[i + 1] = 2 * v2 - ic2
      value -= this.highK[stage] * v1 + v2
    }
    return value
  }

  flush(): void {
    this.lowState.fill(0)
    this.highState.fill(0)
    this.currentLowPassHz = this.targetLowPassHz
    this.currentHighPassHz = this.targetHighPassHz
    this.echoSeenGeneration = this.echoGeneration - 1
  }

  reset(): void {
    this.parkEcho()
    this.echoSeenGeneration = this.echoGeneration - 1
    this.targetLowPassHz = OPEN_HZ
    this.targetHighPassHz = OFF_HZ
    this.lowState = new Float32Array(0)
    this.highState = new Float32Array(0)
    this.channelCount = 0
    this.sampleRate = 0
  }
}
