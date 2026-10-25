import { describe, expect, it } from 'vitest'
import {
  classifyMediaError,
  StreamRecovery,
  type RecoveryAction,
} from './StreamRecovery'

function actionsOf(recovery: StreamRecovery, kind: Parameters<StreamRecovery['nextAction']>[0], count: number, src = 's1'): RecoveryAction[] {
  return Array.from({ length: count }, () => recovery.nextAction(kind, src))
}

describe('کلاس‌بندی خطای MediaError', () => {
  it('کد ۳ یعنی decode خراب — بلاصلاح', () => {
    expect(classifyMediaError({ code: 3 })).toBe('FATAL_DECODE')
  })
  it('کد ۲ یعنی شبکه', () => {
    expect(classifyMediaError({ code: 2 })).toBe('NETWORK')
  })
  it('کد ۴ روی منبع = توکن/آدرس منقضی', () => {
    expect(classifyMediaError({ code: 4 })).toBe('TOKEN_OR_URL_EXPIRED')
  })
  it('بدون خطا/کد نامعلوم = UNKNOWN', () => {
    expect(classifyMediaError(null)).toBe('UNKNOWN')
    expect(classifyMediaError({})).toBe('UNKNOWN')
  })
})

describe('خط لولهٔ بازیابی', () => {
  it('خطای توکن: ۲ retry با backoff → resolve تازه → hls → تسلیم', () => {
    const recovery = new StreamRecovery()
    const actions = actionsOf(recovery, 'TOKEN_OR_URL_EXPIRED', 5)

    expect(actions[0]).toEqual({ kind: 'retry-same', delayMs: 400 })
    expect(actions[1]).toEqual({ kind: 'retry-same', delayMs: 800 })
    expect(actions[2]).toEqual({ kind: 'resolve-fresh' })
    expect(actions[3]).toEqual({ kind: 'hls-fallback' })
    expect(actions[4]).toEqual({ kind: 'give-up' })
  })

  it('خطای شبکه: ۲ retry → resolve تازه (شبکه یعنی آدرس تازه احتمالاً درست است) → hls → تسلیم', () => {
    const recovery = new StreamRecovery()
    const actions = actionsOf(recovery, 'NETWORK', 5)
    expect(actions.map((a) => a.kind)).toEqual([
      'retry-same',
      'retry-same',
      'resolve-fresh',
      'hls-fallback',
      'give-up',
    ])
  })

  it('decode خراب: بدون هیچ تلاشی تسلیم', () => {
    const recovery = new StreamRecovery()
    expect(recovery.nextAction('FATAL_DECODE', 's1')).toEqual({ kind: 'give-up' })
    expect(recovery.nextAction('FATAL_DECODE', 's1')).toEqual({ kind: 'give-up' })
  })

  it('پخشِ سالم (markRecovered) بودجه‌ها را از نو می‌دهد', () => {
    const recovery = new StreamRecovery()
    actionsOf(recovery, 'NETWORK', 3) // retry×2 + fresh
    recovery.markRecovered()
    const again = actionsOf(recovery, 'NETWORK', 1)
    expect(again[0]).toEqual({ kind: 'retry-same', delayMs: 400 })
  })

  it('تعویض src، بودجهٔ retry همان src را نو می‌کند ولی بودجهٔ resolve/hls global می‌ماند', () => {
    const recovery = new StreamRecovery()
    actionsOf(recovery, 'NETWORK', 2, 's1') // retry×2 روی s1
    // ترک بعدی — retryهایش از نو
    expect(recovery.nextAction('NETWORK', 's2')).toEqual({ kind: 'retry-same', delayMs: 400 })
    expect(recovery.nextAction('NETWORK', 's2')).toEqual({ kind: 'retry-same', delayMs: 800 })
    expect(recovery.nextAction('NETWORK', 's2').kind).toBe('resolve-fresh')
    // src سوم: retryهای خودش را دارد، ولی resolve تمام شده — مستقیم به hls می‌رسد
    expect(recovery.nextAction('NETWORK', 's3')).toEqual({ kind: 'retry-same', delayMs: 400 })
    expect(recovery.nextAction('NETWORK', 's3')).toEqual({ kind: 'retry-same', delayMs: 800 })
    expect(recovery.nextAction('NETWORK', 's3').kind).toBe('hls-fallback')
    expect(recovery.nextAction('NETWORK', 's3').kind).toBe('give-up')
  })

  it('reset کامل (ترک تازه از صف) همه‌چیز را نو می‌کند', () => {
    const recovery = new StreamRecovery()
    actionsOf(recovery, 'NETWORK', 4, 's1')
    recovery.reset()
    expect(recovery.nextAction('NETWORK', 's1')).toEqual({ kind: 'retry-same', delayMs: 400 })
  })

  it('isExhausted فقط برای همان src خسته‌شده true است', () => {
    const recovery = new StreamRecovery()
    actionsOf(recovery, 'NETWORK', 5, 's1') // تا تسلیم
    expect(recovery.isExhausted('s1')).toBe(true)
    expect(recovery.isExhausted('s2')).toBe(false)
  })

  it('بودجه‌های سفارشی احترام می‌شوند', () => {
    const recovery = new StreamRecovery({ maxSameRetries: 0, maxFreshAttempts: 2, maxHlsAttempts: 0 })
    expect(recovery.nextAction('TOKEN_OR_URL_EXPIRED', 's').kind).toBe('resolve-fresh')
    expect(recovery.nextAction('TOKEN_OR_URL_EXPIRED', 's').kind).toBe('resolve-fresh')
    expect(recovery.nextAction('TOKEN_OR_URL_EXPIRED', 's').kind).toBe('give-up')
  })
})
