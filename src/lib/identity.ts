/**
 * «هویتِ حساب عوض شد».
 *
 * ورود و خروج بدونِ رفرشِ صفحه اتفاق می‌افتد، ولی چند استور داده‌شان را فقط یک
 * بار — در لحظه‌ی لودِ ماژول — از `localStorage` می‌خوانند. بدونِ این رویداد،
 * کاربرِ تازه در همان تب تاریخچه‌ی جستجو، «ادامه بده»، سنجاق‌های آفلاین و صفِ
 * دانلودِ حسابِ قبلی را می‌دید. کلیدهای حساب‌محور جلوی نشتِ *ذخیره‌شده* را
 * می‌گیرند؛ این رویداد جلوی نشتِ *درونِ حافظه* را.
 *
 * رویدادِ DOM (نه ایمپورتِ استورِ حساب) چون استورِ حساب خودش به لایه‌ی API
 * وابسته است و اگر استورها آن را ایمپورت کنند یک حلقه‌ی وابستگی می‌سازند —
 * همان دلیلی که `onUnauthorized` و `setMediaResolver` هم از callback استفاده
 * می‌کنند. ضمناً هیچ استوری مجبور نیست برای عضو شدن در این قرارداد چیزی
 * صادر کند.
 */

const EVENT = 'musicbazi:identity'

/** `detail` عمداً ندارد: مصرف‌کننده فقط کلیدِ حساب‌محور را دوباره می‌خواند. */
export function emitIdentityChange(): void {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new CustomEvent(EVENT))
}

/** گوش‌دادن به تعویضِ هویت. برگشتی، لغوش می‌کند. */
export function onIdentityChange(run: () => void): () => void {
  if (typeof window === 'undefined') return () => {}
  window.addEventListener(EVENT, run)
  return () => window.removeEventListener(EVENT, run)
}
