import { apiUrl } from './server'

/**
 * لایه‌ی ارتباط با ویزاردِ راه‌اندازی (`server/app/setup.py`).
 *
 * جدا از `MusicApi` است چون آن اینترفیس را مود دمو هم پیاده می‌کند، و در مود
 * دمو هیچ سروری نیست که بشود از کلید پرسید. این‌ها فقط در `VITE_API_MODE=http`
 * صدا زده می‌شوند.
 */

export type SetupKey =
  | 'MUSICBAZI_SPOTIFY_CLIENT_ID'
  | 'MUSICBAZI_SPOTIFY_CLIENT_SECRET'
  | 'MUSICBAZI_GENIUS_ACCESS_TOKEN'
  | 'MUSICBAZI_ACOUSTID_KEY'
  | 'MUSICBAZI_AUDD_TOKEN'
  | 'MUSICBAZI_GEMINI_API_KEY'
  | 'MUSICBAZI_TELEGRAM_BOT_TOKEN'
  | 'MUSICBAZI_PROXY'
  | 'MUSICBAZI_YTDLP_PROXY'
  | 'MUSICBAZI_COOKIES_FILE'
  | 'MUSICBAZI_COOKIES_BROWSER'

export type TestGroup =
  | 'spotify'
  | 'genius'
  | 'acoustid'
  | 'audd'
  | 'gemini'
  | 'telegram'
  | 'proxy'

export interface SetupState {
  done: boolean
  /** کلیدهایی که از قبل ست‌اند — فقط ۴ رقمِ آخر، نه خودِ کلید */
  set: Partial<Record<SetupKey, string>>
  /** چیزی روی دیسک هست که سرور هنوز نخوانده */
  restartNeeded: boolean
  env: {
    ffmpeg: boolean
    jsRuntime: string | null
    potoken: boolean
    cookies: boolean
    proxy: boolean
    internet: boolean
    container: boolean
  }
}

export interface TestResult {
  ok: boolean
  detail: string
}

/**
 * `null` یعنی سرور جواب نداد — که با «جواب داد و گفت تنظیم نیست» یکی نیست.
 * در حالتِ اول دروازه‌ی ویزارد باز نمی‌ماند؛ `OfflineBar` همان کار را بهتر می‌کند.
 */
export async function fetchSetupState(signal?: AbortSignal): Promise<SetupState | null> {
  try {
    const res = await fetch(apiUrl('/api/setup'), { signal })
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
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ key, values }),
    signal,
  })
  if (!res.ok) return { ok: false, detail: await errorText(res) }
  return (await res.json()) as TestResult
}

export async function saveSetup(
  values: Partial<Record<SetupKey, string>>,
  opts: { restart?: boolean; done?: boolean } = {},
): Promise<{ ok: boolean; changed: string[]; restarting: boolean; manualRestart: boolean }> {
  const res = await fetch(apiUrl('/api/setup/save'), {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ values, restart: opts.restart ?? true, done: opts.done ?? false }),
  })
  if (!res.ok) throw new Error(await errorText(res))
  return res.json()
}

export async function uploadCookies(file: File): Promise<{ ok: boolean; youtube: number; cookies: number }> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(apiUrl('/api/setup/cookies'), { method: 'POST', body: form })
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
 */
export async function fetchVibeStatus(signal?: AbortSignal): Promise<{ llm: boolean; model: string | null } | null> {
  try {
    const res = await fetch(apiUrl('/api/health'), { cache: 'no-store', signal })
    if (!res.ok) return null
    const body = (await res.json()) as { features?: { vibeLlm?: boolean; vibeModel?: string | null } }
    const f = body.features
    if (!f) return null
    return { llm: Boolean(f.vibeLlm), model: f.vibeModel ?? null }
  } catch {
    return null
  }
}

/**
 * تا سرور برگردد صبر می‌کند.

 * ری‌استارت از سمتِ خودِ سرور انجام می‌شود، پس مرورگر نمی‌تواند منتظرِ پاسخِ
 * همان درخواست بماند — آن درخواست با سرور می‌میرد. تنها راهِ دیدنِ «بالا آمد»،
 * پرسیدنِ دوباره است.
 */
export async function waitForServer(timeoutMs = 45_000): Promise<boolean> {
  const deadline = Date.now() + timeoutMs
  // یک‌ایستِ کوتاه قبل از اولین پرسش: سرور هنوز نفرستاده که دارد می‌میرد
  await new Promise((r) => setTimeout(r, 1200))
  while (Date.now() < deadline) {
    try {
      const res = await fetch(apiUrl('/api/health'), { cache: 'no-store' })
      if (res.ok) return true
    } catch {
      // در حالِ خاموش/روشن شدن — طبیعی است
    }
    await new Promise((r) => setTimeout(r, 1000))
  }
  return false
}
