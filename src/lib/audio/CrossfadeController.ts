/**
 * کنترلر کراس‌فید همتای دوگانه — پورت `transition/CrossfadeController.kt`.
 *
 * معماری همان است: دو «دک» همیشه زنده‌اند (فعال + ذخیره) و این کنترلر با یک
 * state machine چهارفازی تصمیم می‌گیرد کی دک ذخیره زیر دک فعال بالا بیاید:
 *
 *   IDLE → پایش؛ وقتی به پایان ترک نزدیک شدیم وارد ARMING می‌شود
 *   ARMING → دک بعدی آماده می‌شود؛ به‌محض ورود به پنجره فید، FADING
 *   FADING → فید توان‌برابر؛ در میانه (t ≥ 0.5) نقش دک‌ها عوض می‌شود
 *   BAILING → لغو تمیز؛ دک‌ها به حالت عادی برمی‌گردند
 *
 * تفاوت حساب‌شده با کاتلین:
 *  - فید با `setValueCurveAtTime` روی audio thread زمان‌بندی می‌شود نه با
 *    تنظیم volume هر ۳۰ms (روی وب، نوشتن پارامتر از main thread صداِ زیپر
 *    می‌دهد). کنترلر فقط فرمان شروع می‌دهد و برای handoff/completion تیک می‌زند.
 *  - «هیچ‌چیز تا resolve شدنِ startIncoming تثبیت نمی‌شود»: اگر `play()` دک
 *    incoming رد شد (autoplay policy، فایل رفته)، فید شروع نشده — ترک فعلی
 *    دست‌نخورده تا ENDED می‌رود. کاتلین این مشکل را ندارد چون ExoPlayer
 *    playWhenReady همیشه «موفق» است.
 *  - زمان فید با `performance.now()` مطلق حساب می‌شود نه شمارش تیک؛ در تب
 *    پس‌زمینه که تایمرها throttle می‌شوند، t نباید کند شود.
 *
 * کنترلر هیچ چیزی درباره `<audio>` و Web Audio نمی‌داند — همه‌چیز تزریقی است
 * و با دک ساختگی تست می‌شود.
 */

export type CrossfadePhase = 'IDLE' | 'ARMING' | 'FADING' | 'BAILING'

/** مشابه `TransitionLock` اندروید — کراس‌فید و ارتقای کیفیت با هم نمی‌جنگند */
export const TransitionLock = {
  isCrossfadeActive: false,
  /** رزرو شده برای QualityEngine؛ فعلاً هیچ‌کس true‌اش نمی‌کند */
  isQualityUpgradeActive: false,
}

export const MIN_FADE_MS = 500
export const MAX_FADE_MS = 12000
/** چقدر قبل از پنجره فید، آماده‌سازی شروع شود */
export const ARM_LEAD_MS = 2500

const IDLE_STEP_MS = 250
const ARM_STEP_MS = 50
const FADE_STEP_MS = 30

/** زیر این طول فید، کراس‌فید شنیده نمی‌شود و فقط ریسک پرش دارد */
export const MIN_CROSSFADE_SECONDS = 0.5

/** گِین‌های توان‌برابر یک نقطه t ∈ [0,1] از فید */
export function equalPowerVolumes(t: number): { out: number; in: number } {
  const clamped = Math.min(1, Math.max(0, t))
  const theta = clamped * (Math.PI / 2)
  return { out: Math.cos(theta), in: Math.sin(theta) }
}

/**
 * هدررومِ ترکیب — جلوی کلیپِ جمع دو ترک در میانه فید.
 * `1/√(out+in)` کلمپ به [۰٫۷۰۷، ۱]؛ همان فرمول `driveFade` اندروید.
 */
export function blendHeadroom(outVol: number, inVol: number): number {
  const sum = outVol + inVol
  if (sum <= 0) return 1
  return Math.min(1, Math.max(1 / Math.SQRT2, 1 / Math.sqrt(sum)))
}

/** وضعیت لحظه‌ای دک فعال که کنترلر برای تصمیم‌گیری می‌خواند */
export interface CrossfadeActiveInfo<D> {
  /** شناسه‌ی دک — همان که به onHandoff/onBail برمی‌گردد */
  ref: D
  positionMs: number
  /** ۰ یا نامتنهای یعنی «متادیتا نیامده» — ارم نمی‌کنیم */
  durationMs: number
  isPlaying: boolean
}

/**
 * قلاب‌های تزریقی. `startIncoming` تنها کار async است: منبع را روی دک ذخیره
 * می‌نشانَد و پخش را شروع می‌کند. resolve یعنی «واقعاً صدا می‌دهد»؛ reject
 * یعنی «هیچ اتفاقی نیفتاده» — ترک فعلی باید دست‌نخورده بماند.
 */
export interface CrossfadeHooks<D> {
  active(): CrossfadeActiveInfo<D> | null
  standby(): D | null
  crossfadeSeconds(): number
  startIncoming(incoming: D): Promise<void>
  /** پس از resolve شدنِ startIncoming — رمپ‌های توان‌برابر اینجا زمان‌بندی می‌شوند */
  beginFadeCurve(seconds: number): void
  onHandoff(outgoing: D, incoming: D): void
  onBlendHeadroom(headroom: number): void
  /**
   * پایان/لغو فید: پاک‌سازی دک خروجی (توقف، آزادسازی منبع) و بازگرداندن گین‌ها.
   * هم در پایان موفق فید صدا زده می‌شود هم در bail — تمایز برای پیاده‌سازی مهم نیست.
   */
  onBail(outgoing: D | null, incoming: D | null): void
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

export class CrossfadeController<D> {
  private phase: CrossfadePhase = 'IDLE'
  private ticker: ReturnType<typeof setInterval> | null = null

  private fadeDurationMs = 0
  private fadeStartMs = 0
  private handedOff = false
  private outgoing: D | null = null
  private incoming: D | null = null
  /** startIncoming در جریان است — تیکِ بعدی نباید دوباره بخواهد شروعش کند */
  private fadePending = false

  /**
   * ساعت تزریقی فقط برای تست است (fake timers روی performance.now قابل اطمینان
   * نیستند)؛ در production همان `performance.now()`.
   */
  constructor(
    private readonly hooks: CrossfadeHooks<D>,
    private readonly clock: () => number = nowMs,
  ) {}

  getPhase(): CrossfadePhase {
    return this.phase
  }

  /** همان `start()` کاتلین — حلقه تیک تا release زنده است */
  start(): void {
    this.restartTicker()
  }

  release(): void {
    this.stopTicker()
    this.outgoing = null
    this.incoming = null
    this.handedOff = false
    this.fadePending = false
    this.hooks.onBlendHeadroom(1)
    TransitionLock.isCrossfadeActive = false
    this.phase = 'IDLE'
  }

  /** skip/next/seek/خطا/load صریح — هر ترنزیشن در جریان را می‌کشد */
  notifyInterruption(): void {
    if (this.phase !== 'IDLE') this.bail()
  }

  bail(): void {
    if (this.phase === 'IDLE') return
    const { outgoing, incoming } = this
    this.stopTicker()
    this.hooks.onBail(outgoing, incoming)
    this.outgoing = null
    this.incoming = null
    this.handedOff = false
    this.fadePending = false
    this.hooks.onBlendHeadroom(1)
    TransitionLock.isCrossfadeActive = false
    this.phase = 'IDLE'
    this.restartTicker()
  }

  /**
   * معادل فاز IDLE از تیک — ولی جداگانه public شده تا موتور بتواند خارج از
   * ریتم ۲۵۰ms هم (مثلاً بعد از setNext یا تغییر crossfadeSeconds) ارم کند.
   */
  poll(): void {
    if (this.phase === 'IDLE') this.considerAutoTransition()
  }

  private restartTicker(): void {
    this.stopTicker()
    const step =
      this.phase === 'ARMING' ? ARM_STEP_MS : this.phase === 'FADING' ? FADE_STEP_MS : IDLE_STEP_MS
    this.ticker = setInterval(() => this.tick(), step)
  }

  private stopTicker(): void {
    if (this.ticker !== null) clearInterval(this.ticker)
    this.ticker = null
  }

  private tick(): void {
    switch (this.phase) {
      case 'IDLE':
        this.considerAutoTransition()
        return
      case 'ARMING':
        this.driveArming()
        return
      case 'FADING':
        this.driveFade()
        return
      case 'BAILING':
        this.bail()
        return
    }
  }

  private considerAutoTransition(): void {
    if (TransitionLock.isQualityUpgradeActive) return
    const seconds = this.hooks.crossfadeSeconds()
    if (seconds < MIN_CROSSFADE_SECONDS) return

    const info = this.hooks.active()
    if (!info || !info.isPlaying) return
    const { durationMs, positionMs } = info
    if (!Number.isFinite(durationMs) || durationMs <= 0) return

    const remaining = durationMs - positionMs
    const fadeMs = clamp(seconds * 1000, MIN_FADE_MS, MAX_FADE_MS)

    // دو گاردِ وب که کاتلین ندارد و عمداً حفظ شده‌اند:
    //  ۱) ترکی کوتاه‌تر از خود فید را محو نکن
    //  ۲) متادیتای مدتِ جعلیِ فرمت‌های streaming: تا پخش‌شده از ۲ ثانیه
    //     نگذشته، ارم نکن
    if (durationMs <= fadeMs) return
    if (positionMs < 2000) return

    if (remaining <= fadeMs + ARM_LEAD_MS && remaining > 0) {
      this.beginArming(fadeMs)
    }
  }

  private beginArming(fadeMs: number): void {
    if (this.phase !== 'IDLE') return
    const info = this.hooks.active()
    const incoming = this.hooks.standby()
    if (!info || incoming === null) return

    TransitionLock.isCrossfadeActive = true
    this.fadeDurationMs = fadeMs
    this.outgoing = info.ref
    this.incoming = incoming
    this.phase = 'ARMING'
    this.restartTicker()
  }

  private driveArming(): void {
    const info = this.hooks.active()
    if (!info || info.ref !== this.outgoing) {
      this.bail()
      return
    }
    const remaining = info.durationMs - info.positionMs
    if (!Number.isFinite(remaining) || remaining <= this.fadeDurationMs) {
      this.beginFade()
    }
  }

  private beginFade(): void {
    const incoming = this.incoming
    const outgoing = this.outgoing
    if (incoming === null || outgoing === null) {
      this.bail()
      return
    }
    if (this.fadePending) return
    this.fadePending = true

    void this.hooks
      .startIncoming(incoming)
      .then(() => {
        this.fadePending = false
        // حین await ممکن است seek/stop آمده باشد — تثبیت فقط اگر هنوز همان فیدیم
        if (this.phase !== 'ARMING' || this.incoming !== incoming) return
        this.phase = 'FADING'
        this.fadeStartMs = this.clock()
        this.handedOff = false
        this.restartTicker()
        this.hooks.beginFadeCurve(this.fadeDurationMs / 1000)
      })
      .catch(() => {
        // شکست startIncoming یعنی هیچ‌چیز تثبیت نشده: دک‌ها و صف دست‌نخورده،
        // مسیر عادی ended ترک بعدی را بالا می‌آورد — بدون فید، بدون سکوت
        this.fadePending = false
        this.bail()
      })
  }

  private driveFade(): void {
    const outgoing = this.outgoing
    const incoming = this.incoming
    if (outgoing === null || incoming === null) {
      this.bail()
      return
    }

    const elapsed = this.clock() - this.fadeStartMs
    const t = clamp(elapsed / this.fadeDurationMs, 0, 1)
    const { out, in: volIn } = equalPowerVolumes(t)
    this.hooks.onBlendHeadroom(blendHeadroom(out, volIn))

    if (t >= 0.5 && !this.handedOff) {
      this.handedOff = true
      this.hooks.onHandoff(outgoing, incoming)
    }

    if (t >= 1) this.finishFade()
  }

  private finishFade(): void {
    const outgoing = this.outgoing
    const incoming = this.incoming
    this.outgoing = null
    this.incoming = null
    this.handedOff = false
    this.fadePending = false
    this.hooks.onBlendHeadroom(1)
    if (outgoing !== null && incoming !== null) this.hooks.onBail(outgoing, incoming)
    TransitionLock.isCrossfadeActive = false
    this.phase = 'IDLE'
    this.restartTicker()
  }
}

function nowMs(): number {
  return typeof performance !== 'undefined' ? performance.now() : Date.now()
}
