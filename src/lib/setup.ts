import { token } from './auth'
import { apiUrl } from './server'

/**
 * لایه‌ی ارتباط با ویزاردِ راه‌اندازی (`server/app/setup.py`).
 *
 * جدا از `MusicApi` است چون آن اینترفیس را مود دمو هم پیاده می‌کند، و در مود
 * دمو هیچ سروری نیست که بشود از کلید پرسید. این‌ها فقط در `VITE_API_MODE=http`
 * صدا زده می‌شوند.
 *
 * **کلیدها شخصی‌اند.** هر کلید مالِ حسابِ واردشده است، پس هر درخواستی که
 * مقدار می‌فرستد هدرِ `Authorization` را هم می‌برد؛ سرور بی‌توکن را ۴۰۱
 * می‌کند. `GET` اختیاری است چون صفحه باید برای مهمان هم وضعیتِ سرور را نشان
 * بدهد.
 */

/**
 * تنها کلیدهایی که کاربر می‌تواند وارد کند.
 *
 * عمداً کوتاه: پروکسی، SoundCloud، کوکیِ یوتیوب و توکنِ باتِ تلگرام مالِ
 * سرورند. پروکسیِ آزاد یک SSRF می‌شود و بات یک باتِ مشترک است — نه چیزی که
 * بازدیدکننده عوض کند.
 *
 * **کوکیِ یوتیوب شخصی نیست:** کوکی به حسابِ یوتیوبِ سازنده‌اش گره خورده و
 * درست کار کردنش به همان حساب و دستگاه بستگی دارد. یک فایلِ مشترک روی سرور
 * می‌ماند و هر کسی که وارد شود از آن استفاده می‌کند؛ آپلودش هست ولی در لیستِ
 * کلیدهای شخصی نیست.
 */
export type SetupKey =
  | 'MUSICBAZI_SPOTIFY_CLIENT_ID'
  | 'MUSICBAZI_SPOTIFY_CLIENT_SECRET'
  | 'MUSICBAZI_GENIUS_ACCESS_TOKEN'
  | 'MUSICBAZI_ACOUSTID_KEY'
  | 'MUSICBAZI_AUDD_TOKEN'
  | 'MUSICBAZI_GEMINI_API_KEY'

/** گروه‌هایی که سرور می‌تواند بیازماید؛ هر کدام یک سرویسِ بیرونی. */
export type TestGroup = 'spotify' | 'genius' | 'acoustid' | 'audd' | 'gemini'

export interface SetupState {
  /** آیا این حساب یک‌بار ویزارد را دیده یا رد کرده — نه اینکه کلید دارد */
  done: boolean
  /** کلیدهای همین حساب که از قبل ست‌اند — فقط ۴ رقمِ آخر، نه خودِ کلید */
  set: Partial<Record<SetupKey, string>>
  /** وضعیتِ سرور: کاربر نمی‌تواند عوضش کند، ولی باید بداند چرا کار نمی‌کند */
  env: {
    ffmpeg: boolean
    jsRuntime: string | null
    potoken: boolean
    proxy: boolean
    cookies: boolean
    internet: boolean
    container: boolean
  }
  /** تلگرام مالِ سرور است و فقط-خواندنی */
  telegram?: {
    botTokenSet: boolean
    connected: boolean
    botUsername: string | null
  }
}

export interface TestResult {
  ok: boolean
  detail: string
}

function authHeaders(): Record<string, string> {
  const value = token()
  return value ? { authorization: `Bearer ${value}` } : {}
}

/**
 * `null` یعنی سرور جواب نداد — که با «جواب داد و گفت تنظیم نیست» یکی نیست.
 * در حالتِ اول دروازه‌ی ویزارد باز نمی‌ماند؛ `OfflineBar` همان کار را بهتر می‌کند.
 */
export async function fetchSetupState(signal?: AbortSignal): Promise<SetupState | null> {
  try {
    const res = await fetch(apiUrl('/api/setup'), { signal, headers: authHeaders() })
    return res.ok ? ((await res.json()) as SetupState) : null
  } catch {
    return null
  }
}

export async function testSetupKey(
  key: TestGroup,
  values: Partial<Record<SetupKey, string>>,
  signal?: AbortSignal,
): Promise<TestResult> {
  const res = await fetch(apiUrl('/api/setup/test'), {
    method: 'POST',
    headers: { 'content-type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ key, values }),
    signal,
  })
  if (!res.ok) return { ok: false, detail: await errorText(res) }
  return (await res.json()) as TestResult
}

/**
 * ذخیره در دیتابیسِ همین حساب. بدونِ ری‌استارت: مقدارها از درخواستِ بعدی زنده
 * خوانده می‌شوند، پس پاسخ فقط می‌گوید چه چیزی عوض شد.
 */
export async function saveSetup(
  values: Partial<Record<SetupKey, string>>,
  opts: { done?: boolean } = {},
): Promise<{ ok: boolean; changed: string[]; done: boolean }> {
  const res = await fetch(apiUrl('/api/setup/save'), {
    method: 'POST',
    headers: { 'content-type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ values, done: opts.done ?? false }),
  })
  if (!res.ok) throw new Error(await errorText(res))
  return res.json()
}

export async function uploadCookies(
  file: File,
): Promise<{ ok: boolean; youtube: number; cookies: number }> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(apiUrl('/api/setup/cookies'), {
    method: 'POST',
    headers: authHeaders(),
    body: form,
  })
  if (!res.ok) throw new Error(await errorText(res))
  return res.json()
}

/** پیامِ خودِ بک‌اند را نشان بده، نه `400 Bad Request` خشک */
async function errorText(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: string }
    if (typeof body.detail === 'string') return body.detail
  } catch {
    // بدنه JSON نبود
  }
  return `${res.status} ${res.statusText}`
}

/**
 * سلامتِ مسیرِ تشخیصِ حال‌وهوا — برای نشانگرِ کوچکِ بالای چت.
 *
 * چرا جدا از `MusicApi`: آن اینترفیس را مود دمو هم پیاده می‌کند و در مود دمو
 * سروری نیست. این هم مثلِ بقیه‌ی این فایل فقط در `VITE_API_MODE=http` صدا
 * زده می‌شود، و `null` یعنی «نمی‌دانیم» — نه «خاموش است».
 *
 * پرچم‌ها per-account حساب می‌شوند، پس هدرِ توکن لازم است؛ وگرنه کاربری که کلید
 * خودش را وارد کرده همیشه «خاموش» می‌دید.
 */
export async function fetchVibeStatus(
  signal?: AbortSignal,
): Promise<{ llm: boolean; model: string | null } | null> {
  try {
    const res = await fetch(apiUrl('/api/health'), {
      cache: 'no-store',
      signal,
      headers: authHeaders(),
    })
    if (!res.ok) return null
    const body = (await res.json()) as {
      features?: { vibeLlm?: boolean; vibeModel?: string | null }
    }
    const f = body.features
    if (!f) return null
    return { llm: Boolean(f.vibeLlm), model: f.vibeModel ?? null }
  } catch {
    return null
  }
}
