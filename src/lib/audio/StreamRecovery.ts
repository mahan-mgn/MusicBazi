/**
 * بازیابی جریان — پورت مفهوم `StreamRecovery.kt` اندروید.
 *
 * اندروید یک نقطهٔ اتصال `StreamRecoveryHandler` دارد («خطای 403/410 یعنی
 * آدرس/توکن منقضی، دوباره resolve کن») که هیچ‌وقت وصل نشده بود. وب این را
 * کامل و واقعی پیاده می‌کند.
 *
 * ساختار: این کلاس فقط «تصمیم» می‌گیرد — بدون شبکه، بدون DOM. اجرای هر
 * اقدام با موتور (`audioEngine.ts`) است که به المنت و استور دسترسی دارد:
 *
 *   retry-same      → همان src دوباره (backoff ۴۰۰ms، ۸۰۰ms) — حداکثر ۲ بار
 *   resolve-fresh   → آدرس تازه از استور (streamUrlFor + media token تازه)
 *   hls-fallback    → hls.js روی همین المنت (فقط برای srcهای خود سرور)
 *   give-up         → تسلیم؛ استور failed نشان می‌دهد و بعد از ۲ خطای
 *                     متوالی خودش به ترک بعدی می‌رود
 *
 * خطای decode هرگز retry نمی‌شود — فایل خراب با تلاش دوباره خراب نمی‌شود.
 */

export type StreamErrorKind =
  /** آدرس/توکن منقضی (403/410) یا منبع دیگر در دسترس نیست */
  | 'TOKEN_OR_URL_EXPIRED'
  | 'NETWORK'
  /** فایل هست ولی قابل رمزگشایی نیست — بلاصلاح */
  | 'FATAL_DECODE'
  | 'UNKNOWN'

export type RecoveryAction =
  | { kind: 'retry-same'; delayMs: number }
  | { kind: 'resolve-fresh' }
  | { kind: 'hls-fallback' }
  | { kind: 'give-up' }

/** کدهای MediaError DOM — نگاشت به نوعِ معنایی */
export const MEDIA_ERROR_KIND: Record<number, StreamErrorKind> = {
  // MEDIA_ERR_ABORTED — معمولاً نتیجهٔ load جدید، نه خطای واقعی
  1: 'UNKNOWN',
  2: 'NETWORK',
  3: 'FATAL_DECODE',
  // MEDIA_ERR_SRC_NOT_SUPPORTED: روی منبع خودِ سرور، عملاً همان 403/410 است
  // (سرور پاسخ خطا می‌دهد و مرورگر codec ناشناخته می‌بیند)؛ منبع بیرونی واقعاً پشتیبانی‌نشدنی است
  4: 'TOKEN_OR_URL_EXPIRED',
}

export function classifyMediaError(error: { code?: number } | null | undefined): StreamErrorKind {
  if (!error || typeof error.code !== 'number') return 'UNKNOWN'
  return MEDIA_ERROR_KIND[error.code] ?? 'UNKNOWN'
}

export interface StreamRecoveryOptions {
  /** تلاش مجدد همان src — پیش‌فرض ۲ (۴۰۰ و ۸۰۰ میلی‌ثانیه) */
  maxSameRetries?: number
  /** resolve تازه از استور — پیش‌فرض ۱ بار */
  maxFreshAttempts?: number
  /** fallback به hls.js — پیش‌فرض ۱ بار */
  maxHlsAttempts?: number
}

const BASE_RETRY_DELAY_MS = 400

export class StreamRecovery {
  private sameRetries = 0
  private freshAttempts = 0
  private hlsAttempts = 0
  private lastSrc: string | null = null

  private readonly maxSameRetries: number
  private readonly maxFreshAttempts: number
  private readonly maxHlsAttempts: number

  constructor(options: StreamRecoveryOptions = {}) {
    this.maxSameRetries = options.maxSameRetries ?? 2
    this.maxFreshAttempts = options.maxFreshAttempts ?? 1
    this.maxHlsAttempts = options.maxHlsAttempts ?? 1
  }

  /** پخشِ سالم دوباره وصل شد — بودجه‌ها از نو */
  markRecovered(): void {
    this.reset()
  }

  /** ترک تازه لود شد — بودجه‌ها از نو */
  reset(): void {
    this.sameRetries = 0
    this.freshAttempts = 0
    this.hlsAttempts = 0
  }

  /**
   * تصمیم بعدی برای خطای `kind` روی `src`.
   *
   * تعویض src بودجه‌های همان src را صفر می‌کند ولی بودجه‌های resolve/hls
   * سرجایشان می‌مانند — این‌ها محافظِ ضد حلقهٔ کل نشست‌اند، نه هر ترک.
   * (ترکِ تازه با reset() کامل نو می‌شود.)
   */
  nextAction(kind: StreamErrorKind, src: string): RecoveryAction {
    if (src !== this.lastSrc) {
      this.lastSrc = src
      this.sameRetries = 0
    }

    if (kind === 'FATAL_DECODE') return { kind: 'give-up' }

    if (this.sameRetries < this.maxSameRetries) {
      this.sameRetries++
      return { kind: 'retry-same', delayMs: BASE_RETRY_DELAY_MS * 2 ** (this.sameRetries - 1) }
    }

    // شبکه یا توکنِ منقضی: آدرس تازه احتمالاً مشکل را حل می‌کند — قبل از hls
    if (
      (kind === 'NETWORK' || kind === 'TOKEN_OR_URL_EXPIRED') &&
      this.freshAttempts < this.maxFreshAttempts
    ) {
      this.freshAttempts++
      return { kind: 'resolve-fresh' }
    }

    if (this.hlsAttempts < this.maxHlsAttempts) {
      this.hlsAttempts++
      return { kind: 'hls-fallback' }
    }

    return { kind: 'give-up' }
  }

  /** آیا این منبع بودجه‌اش تمام شده — برای watchdog که خطای صریح ندارد */
  isExhausted(src: string): boolean {
    if (src !== this.lastSrc) return false
    return (
      this.sameRetries >= this.maxSameRetries &&
      this.freshAttempts >= this.maxFreshAttempts &&
      this.hlsAttempts >= this.maxHlsAttempts
    )
  }
}
