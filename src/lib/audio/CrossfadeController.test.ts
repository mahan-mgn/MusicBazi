import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ARM_LEAD_MS,
  blendHeadroom,
  CrossfadeController,
  equalPowerVolumes,
  MIN_FADE_MS,
  TransitionLock,
  type CrossfadeHooks,
} from './CrossfadeController'

/** شش ثانیه کراس‌فید — عدد راحت برای حساب ARM_LEAD */
const FADE_SECONDS = 6
const FADE_MS = FADE_SECONDS * 1000

/**
 * قلاب‌ها با رشته‌های 'A' (فعال) و 'B' (ذخیره) کار می‌کنند؛ ترک ۲۰۸ ثانیه‌ای
 * طوری انتخاب شده که بازه ارم (fade + lead) داخلش جا شود.
 */
const TRACK_MS = 208_000
/** اولین position که کنترلر گارد «متادیتای جعلی» را رد کند */
const MIN_POSITION_MS = 2000

interface Harness {
  controller: CrossfadeController<string>
  calls: string[]
  setActive(patch: Partial<{ positionMs: number; durationMs: number; isPlaying: boolean; ref: string }>): void
  setStandby(ref: string | null): void
  /** ساعت و تایمرها را با هم جلو می‌برد؛ در IDLE یک poll صریح هم می‌زند */
  advance(ms: number): void
  /** پیشبردِ خالص فید — بدون poll، برای وقتی که وضعیت دک در تست ثابت می‌ماند */
  advanceNoPoll(ms: number): void
  resolveStart(): Promise<void>
  rejectStart(): Promise<void>
}

function makeHarness(options: { crossfadeSeconds?: number; standby?: string | null } = {}): Harness {
  let clock = 0
  let activeRef = 'A'
  let positionMs = MIN_POSITION_MS
  let durationMs = TRACK_MS
  let isPlaying = true
  let standby: string | null = options.standby === undefined ? 'B' : options.standby
  const calls: string[] = []
  let startDeferred: { resolve: () => void; reject: (e: unknown) => void } | null = null

  const hooks: CrossfadeHooks<string> = {
    active: () => ({ ref: activeRef, positionMs, durationMs, isPlaying }),
    standby: () => standby,
    crossfadeSeconds: () => options.crossfadeSeconds ?? FADE_SECONDS,
    startIncoming: (incoming) =>
      new Promise((resolve, reject) => {
        calls.push(`start:${incoming}`)
        startDeferred = { resolve: () => resolve(), reject: () => reject(new Error('play rejected')) }
      }),
    beginFadeCurve: (seconds) => calls.push(`fade:${seconds}`),
    onHandoff: (outgoing, incoming) => calls.push(`handoff:${outgoing}>${incoming}`),
    onBlendHeadroom: (headroom) => calls.push(`headroom:${headroom.toFixed(3)}`),
    onBail: (outgoing, incoming) => calls.push(`bail:${String(outgoing)},${String(incoming)}`),
  }

  const controller = new CrossfadeController(hooks, () => clock)
  controller.start()

  return {
    controller,
    calls,
    setActive(patch) {
      if (patch.ref !== undefined) activeRef = patch.ref
      if (patch.positionMs !== undefined) positionMs = patch.positionMs
      if (patch.durationMs !== undefined) durationMs = patch.durationMs
      if (patch.isPlaying !== undefined) isPlaying = patch.isPlaying
    },
    setStandby(ref) {
      standby = ref
    },
    advance(ms) {
      // poll قبل از تایمرها: رویدادهای خارج از ریتم (مثل setNext تازه) همان
      // لحظه فرصت ارم پیدا کنند و تیک فازِ تازه هم در همین advance بیفتد
      controller.poll()
      clock += ms
      vi.advanceTimersByTime(ms)
      controller.poll()
    },
    advanceNoPoll(ms) {
      clock += ms
      vi.advanceTimersByTime(ms)
    },
    async resolveStart() {
      startDeferred?.resolve()
      startDeferred = null
      await Promise.resolve()
      await Promise.resolve()
    },
    async rejectStart() {
      startDeferred?.reject(new Error('NotAllowedError'))
      startDeferred = null
      await Promise.resolve()
      await Promise.resolve()
    },
  }
}

describe('منحنی‌های توان‌برابر و هدرروم', () => {
  it('جمع توان در همه نقاط فید برابر ۱ است — بدون افت بلندی در تقاطع', () => {
    for (let i = 0; i <= 10; i++) {
      const { out, in: volIn } = equalPowerVolumes(i / 10)
      expect(out * out + volIn * volIn).toBeCloseTo(1, 5)
    }
  })

  it('شروع فید: خروج کامل و ورود سکوت', () => {
    const { out, in: volIn } = equalPowerVolumes(0)
    expect(out).toBeCloseTo(1)
    expect(volIn).toBeCloseTo(0)
  })

  it('میانه فید: هر دو ۰٫۷۰۷', () => {
    const { out, in: volIn } = equalPowerVolumes(0.5)
    expect(out).toBeCloseTo(Math.SQRT1_2, 5)
    expect(volIn).toBeCloseTo(Math.SQRT1_2, 5)
  })

  it('هدرروم در کف ۰٫۷۰۷ می‌ماند و بالای ۱ نمی‌رود', () => {
    expect(blendHeadroom(1, 1)).toBe(1 / Math.SQRT2)
    expect(blendHeadroom(0, 0)).toBe(1)
    expect(blendHeadroom(1, 0)).toBe(1)
    expect(blendHeadroom(Math.SQRT1_2, Math.SQRT1_2)).toBeCloseTo(1 / Math.sqrt(Math.SQRT2), 5)
  })
})

describe('CrossfadeController — state machine', () => {
  beforeEach(() => {
    TransitionLock.isCrossfadeActive = false
    TransitionLock.isQualityUpgradeActive = false
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('دور از پایان ترک، هیچ فازی شروع نمی‌شود', () => {
    const h = makeHarness()
    h.setActive({ positionMs: 10_000 })
    h.advance(1000)
    expect(h.controller.getPhase()).toBe('IDLE')
    expect(h.calls).toEqual([])
  })

  it('نزدیکِ پایان ترک ARMING و پس از resolve شدن پخش، FADING می‌شود', async () => {
    const h = makeHarness()
    // remaining کمی داخلِ بازه ارم (fade + lead)
    h.setActive({ positionMs: TRACK_MS - (FADE_MS + ARM_LEAD_MS) + 100 })
    h.advance(50)

    expect(h.controller.getPhase()).toBe('ARMING')
    expect(TransitionLock.isCrossfadeActive).toBe(true)

    h.setActive({ positionMs: TRACK_MS - FADE_MS })
    h.advance(50)
    expect(h.calls).toContain('start:B')

    await h.resolveStart()
    expect(h.controller.getPhase()).toBe('FADING')
    expect(h.calls.some((c) => c.startsWith('fade:'))).toBe(true)
  })

  it('شکست startIncoming یعنی هیچ‌چیز تثبیت نشده — bail و ترک فعلی دست‌نخورده', async () => {
    const h = makeHarness()
    h.setActive({ positionMs: TRACK_MS - (FADE_MS + ARM_LEAD_MS) + 100 })
    h.advance(50)
    h.setActive({ positionMs: TRACK_MS - FADE_MS })
    h.advance(50)
    expect(h.calls).toContain('start:B')

    await h.rejectStart()
    expect(h.controller.getPhase()).toBe('IDLE')
    expect(h.calls.some((c) => c.startsWith('fade:'))).toBe(false)
    expect(h.calls.some((c) => c.startsWith('handoff:'))).toBe(false)
    expect(TransitionLock.isCrossfadeActive).toBe(false)
  })

  it('startIncoming معلق دوباره start نمی‌زند', async () => {
    const h = makeHarness()
    h.setActive({ positionMs: TRACK_MS - FADE_MS })
    h.advance(50)
    expect(h.calls.filter((c) => c === 'start:B').length).toBeLessThanOrEqual(1)
    h.advance(FADE_MS)
    expect(h.calls.filter((c) => c.startsWith('start:')).length).toBe(1)
  })

  it('در میانه فید handoff دقیقاً یک‌بار می‌آید و در پایان پاک‌سازی انجام می‌شود', async () => {
    const h = makeHarness()
    h.setActive({ positionMs: TRACK_MS - FADE_MS })
    h.advance(50)
    await h.resolveStart()

    h.advanceNoPoll(2000)
    expect(h.calls.some((c) => c.startsWith('handoff:'))).toBe(false)

    h.advanceNoPoll(1200)
    expect(h.calls).toContain('handoff:A>B')

    // بعد از handoff، دک فعال در واقعیت ترکِ تازه از ابتداست — نه همان
    // موقعیتِ نزدیکِ پایان. بدون این، تیکر IDLE در تست دوباره ارم می‌کند.
    h.setActive({ ref: 'B', positionMs: MIN_POSITION_MS })

    h.advanceNoPoll(FADE_MS)
    expect(h.controller.getPhase()).toBe('IDLE')
    expect(TransitionLock.isCrossfadeActive).toBe(false)
    expect(h.calls.filter((c) => c.startsWith('handoff:')).length).toBe(1)
    expect(h.calls).toContain('bail:A,B')
    expect(h.calls).toContain('headroom:1.000')
  })

  it('هدرروم حین فید از ۱ پایین می‌آید و در پایان برمی‌گردد به ۱', async () => {
    const h = makeHarness()
    h.setActive({ positionMs: TRACK_MS - FADE_MS })
    h.advance(50)
    await h.resolveStart()
    h.advanceNoPoll(3000) // میانه فید
    const midHeadroom = h.calls.filter((c) => c.startsWith('headroom:')).at(-1)
    expect(Number(midHeadroom?.split(':')[1])).toBeLessThan(1)
    // همان نکتهٔ handoff: پس از میانهٔ فید، دک فعال ترک تازه است
    h.setActive({ ref: 'B', positionMs: MIN_POSITION_MS })
    h.advanceNoPoll(FADE_MS)
    // هدرروم در پایان فید به ۱ برمی‌گردد (قبل از پاک‌سازی نهایی)
    expect(h.calls).toContain('headroom:1.000')
    expect(h.calls.filter((c) => c.startsWith('headroom:1.000')).length).toBeGreaterThan(0)
  })

  it('seek حین فید فید را bail می‌کند', async () => {
    const h = makeHarness()
    h.setActive({ positionMs: TRACK_MS - FADE_MS })
    h.advance(50)
    await h.resolveStart()
    h.advanceNoPoll(1500)

    h.controller.notifyInterruption()
    expect(h.controller.getPhase()).toBe('IDLE')
    expect(h.calls).toContain('bail:A,B')
    expect(TransitionLock.isCrossfadeActive).toBe(false)
  })

  it('تعویض دک فعال حین ARMING (load صریح) bail می‌کند', () => {
    const h = makeHarness()
    h.setActive({ positionMs: TRACK_MS - (FADE_MS + ARM_LEAD_MS) + 100 })
    h.advance(50)
    expect(h.controller.getPhase()).toBe('ARMING')

    h.setActive({ ref: 'X', positionMs: MIN_POSITION_MS })
    h.advance(50)
    expect(h.controller.getPhase()).toBe('IDLE')
  })

  it('بدون دک ذخیره (setNext خالی) هرگز ارم نمی‌کند', () => {
    const h = makeHarness({ standby: null })
    h.setActive({ positionMs: TRACK_MS - FADE_MS })
    h.advance(500)
    expect(h.controller.getPhase()).toBe('IDLE')
    expect(h.calls).toEqual([])
  })

  it('کراس‌فید زیر حداقل (۰٫۵s) اصلاً فعال نمی‌شود', () => {
    const h = makeHarness({ crossfadeSeconds: 0.3 })
    h.setActive({ durationMs: 30_000, positionMs: 28_000 })
    h.advance(1000)
    expect(h.controller.getPhase()).toBe('IDLE')
    expect(h.calls).toEqual([])
  })

  it('ترک کوتاه‌تر از خود فید محو نمی‌شود', () => {
    const h = makeHarness()
    h.setActive({ durationMs: 4_000, positionMs: 3_500 })
    h.advance(1000)
    expect(h.controller.getPhase()).toBe('IDLE')
  })

  it('کلیمپ سقف: کراس‌فید ۳۰ ثانیه‌ای به ۱۲ ثانیه سقف می‌خورد', async () => {
    const h = makeHarness({ crossfadeSeconds: 30 })
    // بازه ارم با fadeMs کلیمپ‌شده (۱۲s) حساب می‌شود نه ۳۰s
    h.setActive({ positionMs: TRACK_MS - (12_000 + ARM_LEAD_MS) + 100 })
    h.advance(50)
    h.setActive({ positionMs: TRACK_MS - 12_000 })
    h.advance(50)
    await h.resolveStart()
    expect(h.calls).toContain('fade:12')
  })

  it('کلیمپ کف: فید حداقلی ۰٫۵ ثانیه‌ای مجاز است', async () => {
    const h = makeHarness({ crossfadeSeconds: 0.5 })
    h.setActive({ positionMs: TRACK_MS - (MIN_FADE_MS + ARM_LEAD_MS) + 100 })
    h.advance(50)
    expect(h.controller.getPhase()).toBe('ARMING')
    h.setActive({ positionMs: TRACK_MS - MIN_FADE_MS })
    h.advance(50)
    await h.resolveStart()
    expect(h.calls).toContain(`fade:${MIN_FADE_MS / 1000}`)
  })

  it('پخش متوقف، ارم نمی‌کند — حتی اگر remaining کوچک باشد', () => {
    const h = makeHarness()
    h.setActive({ positionMs: TRACK_MS - FADE_MS, isPlaying: false })
    h.advance(1000)
    expect(h.controller.getPhase()).toBe('IDLE')
  })

  it('ارتقای کیفیت در جریان (TransitionLock) مانع ارم می‌شود', () => {
    const h = makeHarness()
    TransitionLock.isQualityUpgradeActive = true
    h.setActive({ positionMs: TRACK_MS - FADE_MS })
    h.advance(1000)
    expect(h.controller.getPhase()).toBe('IDLE')
  })
})
