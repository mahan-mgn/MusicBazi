import { readStored, removeStored, writeStored } from './storage'

/**
 * توکنِ نشست و توکنِ مدیا.
 *
 * جدا از استور نگه داشته شده تا `http.ts` بتواند بدونِ ایمپورت کردنِ استور
 * (و ساختنِ حلقه‌ی وابستگی) به توکن برسد. استور تنها مصرف‌کننده‌ی منطقِ
 * بالاتری است.
 *
 * هیچ‌کدام از توکن‌ها در حافظه‌ی ماژول کش نمی‌شوند: `readStored` ارزان است و
 * کش کردن یعنی یک تبِ دیگر که خروج زده، در این تب دیده نشود.
 */

const TOKEN_KEY = 'auth:token'
const MEDIA_KEY = 'auth:media'
const STAMP_KEY = 'auth:stamp'

/**
 * مهرِ تغییرِ وضعیتِ ورود.
 *
 * رویدادِ `storage` فقط وقتی در تب‌های *دیگر* پرت می‌شود، و همین کافی است:
 * خروج در یک تب باید تب‌های دیگر را هم ببرد. `BroadcastChannel` می‌کرد ولی
 * یک APIِ دیگر است که در WebViewهای قدیمی نیست.
 */
export function token(): string | null {
  const value = readStored(TOKEN_KEY)
  return value && value.trim() ? value : null
}

export function setToken(value: string): void {
  writeStored(TOKEN_KEY, value)
  // توکنِ مدیای قبلی به کاربرِ قبلی تعلق داشت
  removeStored(MEDIA_KEY)
  stamp()
}

export function clearToken(): void {
  removeStored(TOKEN_KEY)
  removeStored(MEDIA_KEY)
  stamp()
}

function stamp(): void {
  writeStored(STAMP_KEY, String(Date.now()))
}

export function onStampChange(run: () => void): () => void {
  if (typeof window === 'undefined') return () => {}
  const handler = (event: StorageEvent) => {
    if (event.key === STAMP_KEY) run()
  }
  window.addEventListener('storage', handler)
  return () => window.removeEventListener('storage', handler)
}

/**
 * توکنِ ذخیره‌شده‌ی مدیا، فقط اگر هنوز منقضی نشده باشد.
 *
 * پنجره‌ی امنیتی یک دقیقه‌ای: توکنی که «تقریباً منقضی» است، وسطِ یک آهنگِ
 * پنج‌دقیقه‌ای می‌میرد و پخش قطع می‌شود.
 */
export function cachedMediaToken(): string | null {
  const raw = readStored(MEDIA_KEY)
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw) as { token?: string; expiresAt?: number }
    if (!parsed.token || !parsed.expiresAt) return null
    if (parsed.expiresAt * 1000 - Date.now() < 60_000) return null
    return parsed.token
  } catch {
    return null
  }
}

export function setMediaToken(value: { token: string; expiresAt: number }): void {
  writeStored(MEDIA_KEY, JSON.stringify(value))
}

export function clearMediaToken(): void {
  removeStored(MEDIA_KEY)
}

/**
 * توکنِ مدیا را به آدرس می‌چسباند.
 *
 * `<audio src>` نمی‌تواند هدر بفرستد، پس توکن در query می‌رود. برای آدرسی که
 * از قبل query دارد (`?track_id=...`) جداکننده درست انتخاب می‌شود.
 */
export function withMediaToken(url: string, media: string | null): string {
  if (!media) return url
  // آدرسی که از قبل `mt` دارد دست نمی‌خورد: `attachMediaToken` روی پاسخ‌های
  // سرور راه می‌رود و اگر سازنده‌ی آدرس هم توکن زده باشد، `mt` دومی ساخته
  // می‌شد که FastAPI فقط اولی را می‌خواند.
  if (/(?:[?&])mt=/.test(url)) return url
  const separator = url.includes('?') ? '&' : '?'
  return `${url}${separator}mt=${encodeURIComponent(media)}`
}

/**
 * آدرسی که به فایلِ کاربر اشاره می‌کند و از راهی می‌آید که هدر نمی‌فرستد.
 *
 * فقط همین پیشوندها: بقیه‌ی `/api/…`ها با `Authorization` می‌آیند و توکنِ
 * اضافه در URL فقط یک جایِ نشتیِ بی‌مورد می‌سازد.
 */
const MEDIA_PATH = /^\/api\/(downloads\/[^/]+\/(file|stream|lyrics|thumb|events)|downloads\/zip\/)/

/**
 * تهیه‌کننده‌ی توکنِ مدیا.
 *
 * `http.ts` نمی‌تواند استور را ایمپورت کند (استور خودش `api` را می‌خواهد)، پس
 * استور خودش را این‌جا ثبت می‌کند — همان الگویی که `onUnauthorized` دارد.
 */
let mediaResolver: (() => Promise<string | null>) | null = null

export function setMediaResolver(run: (() => Promise<string | null>) | null): void {
  mediaResolver = run
}

/**
 * روی پاسخ‌های سرور راه می‌رود و توکنِ مدیا را به آدرس‌های فایل می‌چسباند.
 *
 * چرا این‌جا و نه سرِ هر مصرف‌کننده: همان آدرس‌ها بعداً داخل `<audio src>`،
 * `<img src>` و `EventSource` می‌نشینند و هیچ‌کدام هدر نمی‌فرستند. اگر تزریق
 * پخش‌پخش می‌شد، افزودنِ یک مسیرِ تازه کافی بود تا یکی بی‌توکن بماند.
 *
 * از تهیه‌کننده‌ی ثبت‌شده پرسیده می‌شود (که کش را می‌خواند و فقط وقتی
 * منقضی شده تازه می‌گیرد): یک درخواستِ تازه به‌ازای هر پاسخِ سرور یعنی هر
 * صدازدنِ کتابخانه یک رفت‌وبرگشتِ اضافه.
 */
export async function attachMediaToken<T>(value: T): Promise<T> {
  const media = mediaResolver ? await mediaResolver() : cachedMediaToken()
  if (!media) return value
  return walkMedia(value, media) as T
}

function walkMedia(value: unknown, media: string): unknown {
  if (typeof value === 'string') {
    return MEDIA_PATH.test(value) ? withMediaToken(value, media) : value
  }
  if (Array.isArray(value)) return value.map((item) => walkMedia(item, media))
  if (value && typeof value === 'object') {
    const out: Record<string, unknown> = {}
    for (const [key, item] of Object.entries(value)) out[key] = walkMedia(item, media)
    return out
  }
  return value
}
