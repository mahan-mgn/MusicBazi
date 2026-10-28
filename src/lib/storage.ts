/**
 * `localStorage` امن.
 *
 * دسترسی به `localStorage` سه جور شکست می‌خورد و هر سه در عمل اتفاق می‌افتند:
 *
 *  ۱. **اصلاً وجود ندارد** — محیطِ نودی (همین تست‌ها) یا یک ورکر. خواندنش
 *     `ReferenceError` می‌دهد، نه `null`.
 *  ۲. **خواندنش استثنا پرت می‌کند** — مرورگری که ذخیره‌سازیِ سایت را بسته
 *     (حالتِ خصوصی، iframeِ سندباکس‌شده، «بلاک کردن کوکی‌های شخص ثالث»).
 *  ۳. **نوشتنش استثنا پرت می‌کند** — سهمیه پر است.
 *
 * سه ماژول از قبل هرکدام جداگانه دورش `try/catch` گذاشته بودند و سه‌تای دیگر
 * نه — از جمله `i18n` و `settings` که *در سطحِ ماژول* می‌خواندند. یعنی در آن
 * مرورگرها کلِ اپ قبل از اولین رندر می‌ترکید و کاربر صفحه‌ی سفید می‌دید، بدون
 * اینکه هیچ error boundaryای فرصت کند چیزی نشان بدهد.
 *
 * اینجا همان الگو یک بار نوشته می‌شود: نبودنِ ذخیره‌سازی یعنی «چیزی ذخیره
 * نشده»، نه یک اپِ خراب.
 */

function store(): Storage | null {
  try {
    // خودِ دسترسی به این نام هم می‌تواند پرت کند، پس داخلِ try است
    return typeof localStorage === 'undefined' ? null : localStorage
  } catch {
    return null
  }
}

/**
 * پسوندِ کلیدهای شخصی‌سازی‌شده برای هر حساب.
 *
 * کتابخانه و آمار روی سرور از هم جدا شده‌اند، ولی این چند تکه (تاریخچه‌ی
 * جستجو، «ادامه بده»، سنجاق‌های آفلاین) فقط در مرورگر می‌مانند. با کلیدِ
 * مشترک، حسابِ دوم روی همان دستگاه تاریخچه و آرشیوِ حسابِ اول را می‌دید.
 *
 * **مهمان پسوند نمی‌گیرد** تا داده‌ی نسخه‌ی تک‌کاربره سرِ جایش بماند و
 * کاربرِ بی‌حساب چیزی از دست ندهد.
 */
export function scopedKey(key: string): string {
  const user = currentUserId()
  return user ? `${key}:${user}` : key
}

/**
 * شناسه‌ی کاربرِ فعلی، خوانده از همان محلِ ذخیره‌ی توکن.
 *
 * مستقیم از `localStorage` و نه از `auth.ts`: آن ماژول خودش از این import
 * می‌کند، و کشیدنِ شناسه به داخلِ `auth.ts` یعنی هر استوری که کلید می‌سازد
 * به آن بسته شود. فرمتِ توکن `<user_id>:<exp>:<sig>` است.
 */
function currentUserId(): string | null {
  try {
    const raw = store()?.getItem('auth:token')
    if (!raw) return null
    const id = raw.split(':')[0]?.trim()
    return id && id !== 'local' ? id : null
  } catch {
    return null
  }
}

/** مقدارِ ذخیره‌شده، یا `null` اگر نبود/نشد */
export function readStored(key: string): string | null {
  try {
    return store()?.getItem(key) ?? null
  } catch {
    return null
  }
}

/** همان، ولی با نوعِ محدودشده — برای کلیدهایی که مقدارشان یک اتحادِ رشته‌ای است */
export function readStoredAs<T extends string>(key: string, fallback: T): T {
  return (readStored(key) as T | null) ?? fallback
}

/**
 * عددِ ذخیره‌شده، فقط اگر واقعاً عددِ متناهیِ داخلِ بازه باشد.
 *
 * `Number('')` صفر است و `Number('x')` یعنی NaN — هر دو باید به پیش‌فرض
 * برگردند، وگرنه یک کلیدِ خراب تنظیمات را بی‌صدا صفر می‌کند.
 */
export function readStoredNumber(
  key: string,
  fallback: number,
  { min = 0, max = Number.POSITIVE_INFINITY }: { min?: number; max?: number } = {},
): number {
  const raw = readStored(key)
  if (raw === null || raw.trim() === '') return fallback
  const value = Number(raw)
  return Number.isFinite(value) && value >= min && value <= max ? value : fallback
}

/** ذخیره می‌کند اگر بشود. برگشتِ `false` یعنی نشد — معمولاً اهمیتی ندارد. */
export function writeStored(key: string, value: string): boolean {
  try {
    const target = store()
    if (!target) return false
    target.setItem(key, value)
    return true
  } catch {
    // سهمیه پر است یا ذخیره‌سازی بسته — کارِ در جریان مهم‌تر از یادآوری است
    return false
  }
}

export function removeStored(key: string): void {
  try {
    store()?.removeItem(key)
  } catch {
    // چیزی برای پاک کردن نبود
  }
}
