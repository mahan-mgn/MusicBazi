/**
 * تایپ‌های بیرون‌دادیِ `dsp-worklet.js` به تست هم‌ارزی (فقط از مسیر قلاب تست).
 *
 * کلاس‌های JS نسخهٔ متنیِ همان API کلاس‌های TypeScript هستند — همان امضاها؛
 * این اعلان‌ها فقط برای تست‌اند.
 */
export interface WorkletCurve {
  gainsDb: Float32Array
  qs: Float32Array
  preampDb: number
}

export interface WorkletEqualizerInstance {
  configure(sampleRate: number, channelCount: number): void
  setTarget(curve: WorkletCurve | null, balance: number, enabled: boolean): void
  process(samples: Float32Array, frameCount: number, channelCount: number): void
}

export interface WorkletSpatializerInstance {
  configure(sampleRate: number, channelCount: number): void
  process(samples: Float32Array, frameCount: number, channelCount: number): void
}

export interface WorkletLoudnessInstance {
  gainByMediaId: Record<string, number>
  configure(sampleRate: number, channelCount: number): void
  track(mediaId: string, nextMediaId?: string | null): void
  setBlendTrim(value: number): void
  process(samples: Float32Array, frameCount: number, channelCount: number): void
}

export interface DSPExposed {
  Equalizer: { new (): WorkletEqualizerInstance }
  Spatializer: { new (enabled: boolean): WorkletSpatializerInstance }
  Loudness: { new (): WorkletLoudnessInstance }
}
