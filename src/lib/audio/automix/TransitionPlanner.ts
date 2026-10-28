/*
 * پورت `automix/TransitionPlanner.kt` اندروید — برنامه‌ریز ترنزیشن هوشمند و اتومیکس
 *
 * Copyright (C) 2026 SFG545 / Kushagra Singh / BitChord Contributors, GPL-3.0
 * (پورت‌شده به Music Bazi — همین پرونده هم تحت GPL-3.0 منتشر می‌شود)
 */

export type TransitionStyle = 'EQUAL_POWER' | 'GAPLESS' | 'DJ_BLEND' | 'DJ_FILTER'

export type FilterTransitionVariant = 'SWEEP' | 'BASS_HANDOFF' | 'ECHO_RIDE'

export interface TransitionTrackMeta {
  id: string
  durationMs: number
  title?: string
  artist?: string
  album?: string
  bpm?: number
  key?: string
}

export interface TransitionPlan {
  shouldStart: boolean
  transitionStartMs: number
  fadeSeconds: number
  transitionStyle: TransitionStyle
  filterVariant: FilterTransitionVariant
  bassSwap: boolean
  bassSwapFraction: number
  incomingPlaybackRate: number
  outgoingPlaybackRate: number
  reason: string
}

const MIN_SMART_DURATION_MS = 30_000
const AUTO_MIN_SECONDS = 4.0
const AUTO_MAX_SECONDS = 12.0
const DEFAULT_FADE_SECONDS = 6.0

const BLOCKED_WORDS = /\b(podcast|episode|audiobook|live|concert|performance)\b/i

/**
 * کلیدهای موسیقیایی استاندارد جهت مقایسه هارمونیک (Camelot / Circle of Fifths)
 */
const KEY_INDEX: Record<string, number> = {
  C: 0,
  'C#': 1,
  Db: 1,
  D: 2,
  'D#': 3,
  Eb: 3,
  E: 4,
  F: 5,
  'F#': 6,
  Gb: 6,
  G: 7,
  'G#': 8,
  Ab: 8,
  A: 9,
  'A#': 10,
  Bb: 10,
  B: 11,
}

export function areHarmonicallyCompatible(keyA?: string, keyB?: string): boolean {
  if (!keyA || !keyB) return false
  const idxA = KEY_INDEX[keyA.trim()]
  const idxB = KEY_INDEX[keyB.trim()]
  if (idxA === undefined || idxB === undefined) return false
  const diff = Math.abs(idxA - idxB)
  // کلید یکسان، یا فاصلهٔ پنجم کامل (۷ نیم‌پرده = ۱ گام روی چرخهٔ پنجم‌ها)
  return diff === 0 || diff === 7 || diff === 5
}

/**
 * تعیین اینکه آیا تمپوی دو ترک به هم نزدیک است (حداکثر ۱۰٪ تفاوت با تراز اکتاوی)
 */
export function areTemposClose(bpmA?: number, bpmB?: number): boolean {
  if (!bpmA || !bpmB || bpmA <= 0 || bpmB <= 0) return false
  let ratio = bpmA / bpmB
  // تراز اکتاوی (مثلا 70 BPM و 140 BPM)
  while (ratio > 1.5) ratio /= 2
  while (ratio < 0.75) ratio *= 2
  return Math.abs(ratio - 1.0) <= 0.1
}

/**
 * برنامه‌ریزی ترنزیشن بین دو آهنگ بر اساس متادیتا و تنظیمات کاربر
 */
export interface TransitionPlannerOptions {
  /** زمان‌بندی هوشمند ورود و خروج، تطبیق طول فید با ضرب‌آهنگ */
  automix?: boolean
  /** ترنزیشن‌های دی‌جی: فیلتر LPF Sweep و تعویض ساب‌بیس (Bass Swap) */
  smartDj?: boolean
}

export function planTransition(
  outgoing: TransitionTrackMeta | null,
  incoming: TransitionTrackMeta | null,
  userCrossfadeSeconds: number,
  options?: TransitionPlannerOptions | boolean,
): TransitionPlan {
  const automix = typeof options === 'object' ? (options.automix ?? true) : (options ?? true)
  const smartDj = typeof options === 'object' ? (options.smartDj ?? true) : (options ?? true)

  // اگر کاربر کراس‌فید را صفر گذاشته باشد → گپ‌لس
  if (userCrossfadeSeconds <= 0 || !outgoing || !incoming) {
    return {
      shouldStart: false,
      transitionStartMs: outgoing ? outgoing.durationMs : 0,
      fadeSeconds: 0,
      transitionStyle: 'GAPLESS',
      filterVariant: 'SWEEP',
      bassSwap: false,
      bassSwapFraction: 0.5,
      incomingPlaybackRate: 1.0,
      outgoingPlaybackRate: 1.0,
      reason: 'Crossfade disabled or missing track',
    }
  }

  // اگر پادکست، لایو یا کتاب صوتی باشد نباید اتومیکس بخورد
  const textCheck = `${outgoing.title ?? ''} ${outgoing.artist ?? ''}`
  if (BLOCKED_WORDS.test(textCheck)) {
    return {
      shouldStart: false,
      transitionStartMs: Math.max(0, outgoing.durationMs - userCrossfadeSeconds * 1000),
      fadeSeconds: userCrossfadeSeconds,
      transitionStyle: 'EQUAL_POWER',
      filterVariant: 'SWEEP',
      bassSwap: false,
      bassSwapFraction: 0.5,
      incomingPlaybackRate: 1.0,
      outgoingPlaybackRate: 1.0,
      reason: 'Spoken/live content fallback to equal-power',
    }
  }

  // اگر مدت زمان آهنگ خیلی کوتاه باشد
  if (outgoing.durationMs < MIN_SMART_DURATION_MS) {
    return {
      shouldStart: false,
      transitionStartMs: Math.max(0, outgoing.durationMs - userCrossfadeSeconds * 1000),
      fadeSeconds: userCrossfadeSeconds,
      transitionStyle: 'EQUAL_POWER',
      filterVariant: 'SWEEP',
      bassSwap: false,
      bassSwapFraction: 0.5,
      incomingPlaybackRate: 1.0,
      outgoingPlaybackRate: 1.0,
      reason: 'Short track fallback to equal-power',
    }
  }

  // محاسبهٔ زمان فید: اتومیکس زمان بهینه را می‌سنجد، در غیر این صورت زمان دقیق درخواستی کاربر
  const fadeSec = automix
    ? Math.min(AUTO_MAX_SECONDS, Math.max(AUTO_MIN_SECONDS, userCrossfadeSeconds || DEFAULT_FADE_SECONDS))
    : userCrossfadeSeconds

  // اگر ترنزیشن دی‌جی خاموش باشد، فید سادهٔ توان-برابر بدون دستکاری فرکانسی انجام می‌شود
  if (!smartDj) {
    return {
      shouldStart: false,
      transitionStartMs: Math.max(0, outgoing.durationMs - fadeSec * 1000),
      fadeSeconds: fadeSec,
      transitionStyle: 'EQUAL_POWER',
      filterVariant: 'SWEEP',
      bassSwap: false,
      bassSwapFraction: 0.5,
      incomingPlaybackRate: 1.0,
      outgoingPlaybackRate: 1.0,
      reason: 'Smart DJ disabled: clean equal-power crossfade',
    }
  }

  // ترنزیشن‌های دی‌جی (Smart DJ):
  const tempoMatch = areTemposClose(outgoing.bpm, incoming.bpm)
  const keyMatch = areHarmonicallyCompatible(outgoing.key, incoming.key)

  let style: TransitionStyle = 'EQUAL_POWER'
  let variant: FilterTransitionVariant = 'SWEEP'
  let bassSwap = false

  if (tempoMatch) {
    // تمپو نزدیک است → بهترین سبک DJ_BLEND با تعویض فرکانس بیس
    style = 'DJ_BLEND'
    bassSwap = true
    variant = keyMatch ? 'BASS_HANDOFF' : 'SWEEP'
  } else {
    // تمپو دور است یا ناشناخته → فیلتر فرکانسی DJ_FILTER با سوئیپ پایین‌گذر
    style = 'DJ_FILTER'
    variant = 'SWEEP'
  }

  const transitionStartMs = Math.max(0, outgoing.durationMs - fadeSec * 1000)

  return {
    shouldStart: false,
    transitionStartMs,
    fadeSeconds: fadeSec,
    transitionStyle: style,
    filterVariant: variant,
    bassSwap,
    bassSwapFraction: 0.5,
    incomingPlaybackRate: 1.0,
    outgoingPlaybackRate: 1.0,
    reason: `Smart DJ selected ${style} (${variant})`,
  }
}
