/*
 * پوستهٔ AudioWorklet برای زنجیرهٔ DSP موتور صوتی.
 *
 * این فایل مستقل بارگذاری می‌شود (AudioWorklet.addModule) و نباید import
 * داشته باشد. کلاس‌های پردازش داخل آن **کپیِ خط‌به‌خط** کلاس‌های خالص
 * TypeScript هستند:
 *
 *   Equalizer   ← src/lib/audio/dsp/Equalizer.ts   (پورت EqualizerProcessor.kt)
 *   Spatializer ← src/lib/audio/dsp/Spatializer.ts (پورت SpatialAudioProcessor.kt)
 *   Loudness    ← src/lib/audio/dsp/Loudness.ts    (پورت LoudnessProcessor.kt)
 *
 * هم‌ارزیِ این کپی با نسخهٔ TS با تست `dsp-worklet.parity.test.ts` به‌صورت
 * مکانیکی تضمین می‌شود — اگر یکی عوض شود و دیگری نه، تست قرمز می‌شود.
 *
 * پروتکل پیام‌ها (port.postMessage):
 *   { type: 'eq',      curve: { gainsDb, qs, preampDb }, balance }  → اکولایزر
 *   { type: 'spatial', enabled }                                     → فضاساز
 *   { type: 'gain',    mediaId, gain }                               → ثبت گین ترک
 *   { type: 'track',   mediaId, nextMediaId }                        → ترک جاری زنجیره
 *   { type: 'normalize', on }                                        → کلید هم‌ترازی
 *   { type: 'trim',    value }                                       → هدرروم ترکیب
 *   { type: 'boundary' }                                             → اسنپ مرز ترک (گپلس درون‌دکی)
 */

(function () {
  'use strict'

  // =========================================================================
  // کلاس‌های خالص — کپی از نسخهٔ TypeScript (تغییر فقط با تست هم‌ارزی)
  // =========================================================================

  var GLIDE_FRAMES = 64
  var GLIDE_RATE = 0.08
  var SETTLED_DB = 0.01
  var SETTLED_BALANCE = 0.0005
  var MIN_Q = 0.05
  var MIN_HZ = 10
  var MAX_FREQUENCY_FRACTION = 0.45
  var DENORMAL_FLOOR = 1e-12

  var EQ_SLOT_KINDS = ['LOW_SHELF', 'BELL', 'BELL', 'BELL', 'BELL', 'BELL', 'HIGH_SHELF', 'LOW_SHELF', 'BELL', 'HIGH_SHELF']
  var EQ_SLOT_HZ = [60, 150, 400, 1000, 2500, 6000, 14000, 250, 1000, 4000]
  var SLOTS = 10

  function clamp(v, min, max) {
    return Math.min(max, Math.max(min, v))
  }

  function Equalizer() {
    this.targetCurve = null
    this.targetBalance = 0

    this.sampleRate = 0
    this.channelCount = 0

    this.currentGainDb = new Float32Array(SLOTS)
    this.currentQ = new Float32Array(SLOTS).fill(0.707)
    this.currentPreampDb = 0
    this.currentBalance = 0

    this.coeffA1 = new Float32Array(SLOTS)
    this.coeffA2 = new Float32Array(SLOTS)
    this.coeffA3 = new Float32Array(SLOTS)
    this.mixInput = new Float32Array(SLOTS)
    this.mixBand = new Float32Array(SLOTS)
    this.mixLow = new Float32Array(SLOTS)

    this.activeSlots = new Int32Array(SLOTS)
    this.running = new Uint8Array(SLOTS)
    this.state = new Float32Array(0)
    this.channelGain = new Float32Array(0)
  }

  Equalizer.prototype.setTarget = function (curve, balance, enabled) {
    this.targetCurve = enabled ? curve : null
    this.targetBalance = enabled ? clamp(balance, -1, 1) : 0
  }

  Equalizer.prototype.configure = function (sampleRate, channelCount) {
    this.sampleRate = sampleRate
    this.channelCount = channelCount
    var requiredSize = channelCount * SLOTS * 2
    if (this.state.length !== requiredSize) this.state = new Float32Array(requiredSize)
    if (this.channelGain.length !== channelCount) {
      this.channelGain = new Float32Array(channelCount)
      for (var c = 0; c < channelCount; c++) this.channelGain[c] = 1
    }
    this.running.fill(0)
    this.snapToTarget()
  }

  Equalizer.prototype.process = function (samples, frameCount, channelCount) {
    if (frameCount === 0 || this.channelCount < 1 || this.sampleRate <= 0) return
    var tuningCurve = this.targetCurve
    if (tuningCurve === null && this.isSettledFlat()) return

    var remaining = frameCount
    var frameOffset = 0
    while (remaining > 0) {
      var subBlock = Math.min(remaining, GLIDE_FRAMES)
      this.glideTowards(tuningCurve)
      var active = this.prepareSections()
      this.prepareChannelGains()

      for (var f = 0; f < subBlock; f++) {
        var baseIdx = (frameOffset + f) * channelCount
        for (var channel = 0; channel < channelCount; channel++) {
          var sample = samples[baseIdx + channel]
          for (var index = 0; index < active; index++) {
            sample = this.section(this.activeSlots[index], channel, sample)
          }
          samples[baseIdx + channel] = sample * this.channelGain[channel]
        }
      }
      this.flushDenormals(active)
      frameOffset += subBlock
      remaining -= subBlock
    }
  }

  Equalizer.prototype.snapToTarget = function () {
    if (this.targetCurve === null) {
      this.currentGainDb.fill(0)
      this.currentQ.fill(0.707)
      this.currentPreampDb = 0
      this.currentBalance = 0
      return
    }
    this.currentGainDb.set(this.targetCurve.gainsDb)
    this.currentQ.set(this.targetCurve.qs)
    this.currentPreampDb = this.targetCurve.preampDb
    this.currentBalance = this.targetBalance
  }

  Equalizer.prototype.glideTowards = function (targetCurve) {
    for (var slot = 0; slot < SLOTS; slot++) {
      var targetGainDb = targetCurve === null ? 0 : targetCurve.gainsDb[slot]
      var targetQ = targetCurve === null ? 0.707 : targetCurve.qs[slot]
      this.currentGainDb[slot] += (targetGainDb - this.currentGainDb[slot]) * GLIDE_RATE
      var from = Math.log(Math.max(MIN_Q, this.currentQ[slot]))
      var to = Math.log(Math.max(MIN_Q, targetQ))
      this.currentQ[slot] = Math.exp(from + (to - from) * GLIDE_RATE)
    }
    var targetPreamp = targetCurve === null ? 0 : targetCurve.preampDb
    this.currentPreampDb += (targetPreamp - this.currentPreampDb) * GLIDE_RATE
    this.currentBalance += (this.targetBalance - this.currentBalance) * GLIDE_RATE
  }

  Equalizer.prototype.isSettledFlat = function () {
    if (Math.abs(this.currentBalance) >= SETTLED_BALANCE) return false
    if (Math.abs(this.currentPreampDb) >= SETTLED_DB) return false
    for (var slot = 0; slot < SLOTS; slot++) {
      if (Math.abs(this.currentGainDb[slot]) >= SETTLED_DB) return false
    }
    return true
  }

  Equalizer.prototype.prepareSections = function () {
    var active = 0
    for (var slot = 0; slot < SLOTS; slot++) {
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

  Equalizer.prototype.updateCoefficients = function (slot) {
    if (this.sampleRate <= 0) return
    var kind = EQ_SLOT_KINDS[slot]
    var hz = EQ_SLOT_HZ[slot]
    var a = Math.pow(10, this.currentGainDb[slot] / 40)
    var q = Math.max(MIN_Q, this.currentQ[slot])
    var usable = clamp(hz, MIN_HZ, this.sampleRate * MAX_FREQUENCY_FRACTION)
    var base = Math.tan((Math.PI * usable) / this.sampleRate)
    var g, k
    if (kind === 'BELL') {
      g = base
      k = 1 / (q * a)
      this.mixInput[slot] = 1
      this.mixBand[slot] = k * (a * a - 1)
      this.mixLow[slot] = 0
    } else if (kind === 'LOW_SHELF') {
      g = base / Math.sqrt(a)
      k = 1 / q
      this.mixInput[slot] = 1
      this.mixBand[slot] = k * (a - 1)
      this.mixLow[slot] = a * a - 1
    } else {
      g = base * Math.sqrt(a)
      k = 1 / q
      this.mixInput[slot] = a * a
      this.mixBand[slot] = k * (1 - a) * a
      this.mixLow[slot] = 1 - a * a
    }
    var d = 1 / (1 + g * (g + k))
    this.coeffA1[slot] = d
    this.coeffA2[slot] = g * d
    this.coeffA3[slot] = g * (g * d)
  }

  Equalizer.prototype.prepareChannelGains = function () {
    var preamp = Math.pow(10, this.currentPreampDb / 20)
    if (this.channelCount === 2) {
      this.channelGain[0] = preamp * Math.min(1, 1 - this.currentBalance)
      this.channelGain[1] = preamp * Math.min(1, 1 + this.currentBalance)
    } else {
      for (var c = 0; c < this.channelCount; c++) this.channelGain[c] = preamp
    }
  }

  Equalizer.prototype.section = function (slot, channel, input) {
    var i = (channel * SLOTS + slot) * 2
    var ic1 = this.state[i]
    var ic2 = this.state[i + 1]
    var v3 = input - ic2
    var v1 = this.coeffA1[slot] * ic1 + this.coeffA2[slot] * v3
    var v2 = ic2 + this.coeffA2[slot] * ic1 + this.coeffA3[slot] * v3
    this.state[i] = 2 * v1 - ic1
    this.state[i + 1] = 2 * v2 - ic2
    return this.mixInput[slot] * input + this.mixBand[slot] * v1 + this.mixLow[slot] * v2
  }

  Equalizer.prototype.clearState = function (slot) {
    for (var channel = 0; channel < this.channelCount; channel++) {
      var i = (channel * SLOTS + slot) * 2
      this.state[i] = 0
      this.state[i + 1] = 0
    }
  }

  Equalizer.prototype.flushDenormals = function (active) {
    for (var index = 0; index < active; index++) {
      var slot = this.activeSlots[index]
      for (var channel = 0; channel < this.channelCount; channel++) {
        var i = (channel * SLOTS + slot) * 2
        if (Math.abs(this.state[i]) < DENORMAL_FLOOR) this.state[i] = 0
        if (Math.abs(this.state[i + 1]) < DENORMAL_FLOOR) this.state[i + 1] = 0
      }
    }
  }

  // ---- Spatializer --------------------------------------------------------

  var SP_WIDTH_GAIN = 2.5
  var SP_OUTPUT_GAIN = 0.82
  var SP_CROSSFEED_GAIN = 0.2
  var SP_LOWPASS_COEFF = 0.3
  var SP_DELAY_MS = 15

  function Spatializer(enabled) {
    this.enabled = !!enabled
    this.sampleRate = 0
    this.channelCount = 0
    this.delayLeft = new Float32Array(0)
    this.delayRight = new Float32Array(0)
    this.delayIndex = 0
    this.lowpassLeft = 0
    this.lowpassRight = 0
  }

  Spatializer.prototype.configure = function (sampleRate, channelCount) {
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
    var delaySamples = Math.max(1, Math.round((sampleRate * SP_DELAY_MS) / 1000))
    if (this.delayLeft.length !== delaySamples) {
      this.delayLeft = new Float32Array(delaySamples)
      this.delayRight = new Float32Array(delaySamples)
    }
    this.flush()
  }

  Spatializer.prototype.process = function (samples, frameCount, channelCount) {
    if (!this.enabled || frameCount === 0) return
    if (channelCount !== 2) return

    var delaySize = this.delayLeft.length
    if (delaySize === 0) return

    var totalSamples = frameCount * 2
    var idx = 0
    var dIdx = this.delayIndex
    var lpL = this.lowpassLeft
    var lpR = this.lowpassRight

    while (idx < totalSamples) {
      var left = samples[idx]
      var right = samples[idx + 1]

      var mid = (left + right) * 0.5
      var side = (left - right) * 0.5 * SP_WIDTH_GAIN

      var delayedRight = this.delayRight[dIdx]
      var delayedLeft = this.delayLeft[dIdx]
      lpL += SP_LOWPASS_COEFF * (delayedRight - lpL)
      lpR += SP_LOWPASS_COEFF * (delayedLeft - lpR)
      samples[idx] = (mid + side + lpL * SP_CROSSFEED_GAIN) * SP_OUTPUT_GAIN
      samples[idx + 1] = (mid - side + lpR * SP_CROSSFEED_GAIN) * SP_OUTPUT_GAIN

      this.delayLeft[dIdx] = left
      this.delayRight[dIdx] = right
      dIdx = (dIdx + 1) % delaySize
      idx += 2
    }

    this.delayIndex = dIdx
    this.lowpassLeft = lpL
    this.lowpassRight = lpR
  }

  Spatializer.prototype.flush = function () {
    this.delayLeft.fill(0)
    this.delayRight.fill(0)
    this.delayIndex = 0
    this.lowpassLeft = 0
    this.lowpassRight = 0
  }

  // ---- Loudness -----------------------------------------------------------

  var LD_LIMIT = 0.985
  var LD_MIN_TRIM = 0.5
  var LD_GLIDE_SECONDS = 0.04
  var LD_RELEASE_SECONDS = 0.08
  var LD_SETTLED = 1e-4

  function Loudness() {
    this.gainByMediaId = {}
    this.mediaId = null
    this.nextMediaId = null
    this.normalize = true

    this.trimTarget = 1
    this.sampleRate = 0
    this.channelCount = 0
    this.currentGain = 1
    this.currentTrim = 1
    this.reduction = 1
    this.glideCoef = 1
    this.releaseCoef = 1
    this.snap = true
  }

  Loudness.prototype.track = function (mediaId, nextMediaId) {
    this.mediaId = mediaId
    this.nextMediaId = nextMediaId === undefined ? null : nextMediaId
  }

  Loudness.prototype.setNormalize = function (on) {
    this.normalize = !!on
  }

  Loudness.prototype.setBlendTrim = function (value) {
    this.trimTarget = clamp(value, LD_MIN_TRIM, 1)
  }

  Loudness.prototype.onStreamBoundary = function () {
    if (this.nextMediaId !== null) this.mediaId = this.nextMediaId
    this.snap = true
  }

  Loudness.prototype.configure = function (sampleRate, channelCount) {
    this.sampleRate = sampleRate
    this.channelCount = channelCount
    this.glideCoef = coefficient(LD_GLIDE_SECONDS, sampleRate)
    this.releaseCoef = coefficient(LD_RELEASE_SECONDS, sampleRate)
    this.snap = true
  }

  Loudness.prototype.targetGain = function () {
    if (this.mediaId === null || !this.normalize) return 1
    var gain = this.gainByMediaId[this.mediaId]
    return typeof gain === 'number' && isFinite(gain) && gain > 0 ? gain : 1
  }

  Loudness.prototype.process = function (samples, frameCount, channelCount) {
    if (frameCount === 0 || channelCount < 1 || this.sampleRate <= 0) return

    var targetGain = this.targetGain()
    var targetTrim = this.trimTarget
    if (this.snap) {
      this.currentGain = targetGain
      this.currentTrim = targetTrim
      this.snap = false
    }

    if (
      targetGain === 1 &&
      targetTrim >= 1 &&
      Math.abs(this.currentGain - 1) < LD_SETTLED &&
      this.currentTrim >= 1 - LD_SETTLED &&
      this.reduction >= 1 - LD_SETTLED
    ) {
      this.currentGain = 1
      this.currentTrim = 1
      this.reduction = 1
      return
    }

    var gain = this.currentGain
    var trim = this.currentTrim
    var gr = this.reduction
    var index = 0
    for (var frame = 0; frame < frameCount; frame++) {
      gain += (targetGain - gain) * this.glideCoef
      trim += (targetTrim - trim) * this.glideCoef
      var scale = gain * trim
      var peak = 0
      for (var channel = 0; channel < channelCount; channel++) {
        var magnitude = Math.abs(samples[index + channel])
        if (magnitude > peak) peak = magnitude
      }
      peak *= scale
      var wanted = peak > LD_LIMIT ? LD_LIMIT / peak : 1
      gr = wanted < gr ? wanted : gr + (wanted - gr) * this.releaseCoef
      var applied = scale * gr
      for (channel = 0; channel < channelCount; channel++) {
        samples[index + channel] *= applied
      }
      index += channelCount
    }
    this.currentGain = gain
    this.currentTrim = trim
    this.reduction = gr
  }

  function coefficient(seconds, rate) {
    return rate <= 0 ? 1 : 1 - Math.exp(-1 / (seconds * rate))
  }

  // =========================================================================
  // پوسته‌های AudioWorkletProcessor — فقط داخل AudioWorkletGlobalScope
  // =========================================================================

  var DSP = { Equalizer: Equalizer, Spatializer: Spatializer, Loudness: Loudness }

  if (typeof AudioWorkletProcessor !== 'undefined' && typeof registerProcessor !== 'undefined') {
    // ورودی MediaElementSource با channelCountMode='explicit' روی ۲ کانال
    // آپ‌میکس می‌شود، پس پردازنده‌ها می‌توانند استریو فرض کنند

    /** اکولایزر */
    var EqProcessor = class extends AudioWorkletProcessor {
      constructor() {
        super()
        this.eq = new Equalizer()
        this.eq.configure(sampleRate, 2)
        this.port.onmessage = (event) => {
          const msg = event.data
          if (msg.type === 'eq') {
            this.eq.setTarget(msg.curve, msg.balance, msg.curve !== null)
          }
        }
      }
      process(inputs, outputs) {
        const input = inputs[0]
        const output = outputs[0]
        if (!input || input.length === 0 || !output || output.length === 0) return true
        const channels = Math.min(2, output.length)
        // کپی اینترلیود از ورودی به خروجی — پردازش در جا
        const frames = input[0].length
        for (let f = 0; f < frames; f++) {
          for (let c = 0; c < channels; c++) {
            output[c][f] = input[Math.min(c, input.length - 1)][f]
          }
        }
        this.eq.process(output[0], frames, channels)
        return true
      }
    }
    registerProcessor('mb-equalizer', EqProcessor)

    /** فضاساز */
    var SpatialProcessor = class extends AudioWorkletProcessor {
      constructor() {
        super()
        this.sp = new Spatializer(false)
        this.sp.configure(sampleRate, 2)
        this.port.onmessage = (event) => {
          const msg = event.data
          if (msg.type === 'spatial') this.sp.enabled = !!msg.enabled
        }
      }
      process(inputs, outputs) {
        const input = inputs[0]
        const output = outputs[0]
        if (!input || input.length === 0 || !output || output.length === 0) return true
        const channels = Math.min(2, output.length)
        const frames = input[0].length
        for (let f = 0; f < frames; f++) {
          for (let c = 0; c < channels; c++) {
            output[c][f] = input[Math.min(c, input.length - 1)][f]
          }
        }
        this.sp.process(output[0], frames, channels)
        return true
      }
    }
    registerProcessor('mb-spatial', SpatialProcessor)

    /** هم‌ترازی بلندی + لیمیتر */
    var LoudnessProcessor = class extends AudioWorkletProcessor {
      constructor() {
        super()
        this.loud = new Loudness()
        this.loud.configure(sampleRate, 2)
        this.port.onmessage = (event) => {
          const msg = event.data
          if (msg.type === 'gain') this.loud.gainByMediaId[msg.mediaId] = msg.gain
          else if (msg.type === 'track') this.loud.track(msg.mediaId, msg.nextMediaId ?? null)
          else if (msg.type === 'normalize') this.loud.setNormalize(msg.on)
          else if (msg.type === 'trim') this.loud.setBlendTrim(msg.value)
          else if (msg.type === 'boundary') this.loud.onStreamBoundary()
          else if (msg.type === 'flush') this.loud.flush()
        }
      }
      process(inputs, outputs) {
        const input = inputs[0]
        const output = outputs[0]
        if (!input || input.length === 0 || !output || output.length === 0) return true
        const channels = Math.min(2, output.length)
        const frames = input[0].length
        for (let f = 0; f < frames; f++) {
          for (let c = 0; c < channels; c++) {
            output[c][f] = input[Math.min(c, input.length - 1)][f]
          }
        }
        this.loud.process(output[0], frames, channels)
        return true
      }
    }
    registerProcessor('mb-loudness', LoudnessProcessor)
  }

  // قلاب تست هم‌ارزی در Node — در مرورگر هیچ‌گاه صدا زده نمی‌شود
  if (typeof globalThis !== 'undefined' && globalThis.__dspWorkletTestHook) {
    globalThis.__dspWorkletTestHook(DSP)
  }
})()
