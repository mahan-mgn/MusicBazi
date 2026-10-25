/*
 * پورت `pcm/AudioBlock.kt` اندروید — بافر interleaved Float32 با استفادهٔ
 * مجدد (بدون تخصیص در حالت پایدار).
 *
 * Copyright (C) 2024-2026 Kushagra Singh / BitChord Contributors, GPL-3.0
 * (پورت‌شده به Music Bazi — همین پرونده هم تحت GPL-3.0 منتشر می‌شود)
 */

/**
 * بلوک صوتی interleaved: `frameCount` فریم × `channelCount` کانال،
 * فریم به فریم کنار هم. پردازنده‌ها در جا (`in-place`) روی samples کار می‌کنند.
 */
export interface AudioBlock {
  samples: Float32Array
  frameCount: number
  channelCount: number
}

/** یک بلوک تازه با ظرفیت خواسته‌شده */
export function createBlock(frameCount: number, channelCount: number): AudioBlock {
  return {
    samples: new Float32Array(frameCount * channelCount),
    frameCount,
    channelCount,
  }
}

/**
 * بلوک ورک‌لت را در AudioBlock می‌پیچد — بدون کپی.
 * ورودی/خروجی AudioWorkletProcessor خودش Float32Array interleaved است.
 */
export function wrapBlock(samples: Float32Array, frameCount: number, channelCount: number): AudioBlock {
  return { samples, frameCount, channelCount }
}
