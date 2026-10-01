import { Capacitor } from '@capacitor/core'

/**
 * آدرس بک‌اند.
 *
 * در مرورگر (دِو یا داکر) فرانت و API روی یک مبدأاند، پس آدرس خالی می‌ماند و
 * همه‌چیز نسبی است — دقیقاً مثل قبل.
 *
 * داخل اپ اندروید ولی چنین چیزی وجود ندارد: صفحه از `https://localhost` سرو
 * می‌شود و `/api/...` یعنی «خودِ اپ»، نه سرور. برای همین آنجا یک آدرس مطلق
 * لازم است که کاربر خودش وارد می‌کند (آی‌پیِ کامپیوتر در شبکه‌ی خانه، یا آدرس
 * تونل). همین یک ماژول تنها جایی است که این تفاوت را می‌داند.
 */

const KEY = 'server:base'
const REMOTE_KEY = 'server:remote'

export function lastRemoteBase(): string {
  try {
    return localStorage.getItem(REMOTE_KEY) ?? ''
  } catch {
    return ''
  }
}

/**
 * آیا داخل پوسته‌ی نیتیو اجرا می‌شویم؟
 *
 * از خودِ Capacitor پرسیده می‌شود، نه از روی مبدأ صفحه: در حالت livereload
 * اپِ نیتیو صفحه را از دِوسرورِ ویت می‌گیرد و آن‌وقت مبدأ چیزی از نیتیو بودن
 * نمی‌گوید. روی وب همین تابع false برمی‌گرداند و بسته‌ی وب هم چیز معناداری
 * از Capacitor با خودش نمی‌برد.
 */
export function isNativeApp(): boolean {
  return Capacitor.isNativePlatform()
}

/**
 * سروری که روی *خودِ گوشی* می‌دود.
 *
 * بک‌اند داخل Termux روی `127.0.0.1:8000` بالا می‌آید (اسکریپتش
 * `scripts/phone-server.sh`). WebView و Termux در یک دستگاه‌اند و یک namespace
 * شبکه را share می‌کنند، پس loopback از داخل اپ همان‌جا می‌رسد — بدون وای‌فای،
 * بدون آی‌پی، بدون هیچ دستگاهِ دیگری.
 *
 * پورت با `MUSICBAZI_PHONE_PORT` عوض می‌شود؛ اگر کسی عوض کرد، همان آدرس را دستی
 * در «آدرس سرور» وارد می‌کند.
 */
export const LOCAL_PORT = 8000

export function localBase(): string {
  return `http://127.0.0.1:${LOCAL_PORT}`
}

/**
 * آیا این آدرس، دستگاهِ خودِ گوشی است؟
 *
 * فقط برای نمایش است — تا کاربر در منو ببیند کتابخانه‌ای که می‌بیند مالِ همین
 * گوشی است نه لپ‌تاپ. loopback با هر دو نامِ رایجش حساب می‌شود چون کسی که
 * آدرس را دستی می‌نویسد ممکن است `localhost` بنویسد.
 */
export function isLocalServer(base = serverBase()): boolean {
  return /^https?:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/i.test(base)
}

/** آدرسِ ذخیره‌شده را تمیز می‌کند: بدون اسلشِ آخر، و بدون `/api` اضافه‌ی کاربر */
export function normalizeBase(raw: string): string {
  let value = raw.trim()
  if (!value) return ''
  // کاربری که فقط «192.168.0.183:8080» می‌نویسد منظورش http است
  if (!/^https?:\/\//i.test(value)) value = `http://${value}`
  value = value.replace(/\/+$/, '')
  // «آدرس سرور» یعنی ریشه؛ اگر کسی /api را هم چسبانده، دوباره اضافه نشود
  value = value.replace(/\/api$/i, '')
  return value
}

let cached: string | null = null

/**
 * `localStorage` همیشه در دسترس نیست — در تست‌های نودی اصلاً وجود ندارد، و در
 * حالت خصوصیِ بعضی مرورگرها خواندنش استثنا پرت می‌کند. نبودش یعنی «آدرسی
 * ذخیره نشده»، نه یک اپِ خراب.
 */
function read(): string {
  try {
    return localStorage.getItem(KEY) ?? ''
  } catch {
    return ''
  }
}

/** ریشه‌ی سرور — رشته‌ی خالی یعنی «همین مبدأ» */
export function serverBase(): string {
  if (cached !== null) return cached
  cached = read()
  return cached
}

export function setServerBase(raw: string): void {
  const value = normalizeBase(raw)
  cached = value
  try {
    if (value) {
      localStorage.setItem(KEY, value)
      if (!isLocalServer(value)) {
        localStorage.setItem(REMOTE_KEY, value)
      }
    } else {
      localStorage.removeItem(KEY)
    }
  } catch {
    // ذخیره نشد — همین اجرا کار می‌کند، دفعه‌ی بعد دوباره پرسیده می‌شود
  }
}

/**
 * جستجوی خودکار برای یافتن سرور موزیک بازی در شبکه محلی (وای‌فای)
 * ساب‌نت‌های رایج (192.168.1.x و 192.168.0.x یا آخرین آی‌پی شناخته‌شده)
 * را روی پورت‌های ۸۰۸۰ و ۸۰۰۰ پینگ می‌کند.
 */
export async function discoverLanServer(onProgress?: (checked: number, total: number) => void): Promise<string | null> {
  const remembered = lastRemoteBase()
  const ports = [8080, 8000]
  const subnets = new Set<string>()

  if (remembered) {
    const match = /https?:\/\/(\d+\.\d+\.\d+)\.\d+(?::(\d+))?/.exec(remembered)
    if (match) {
      subnets.add(match[1])
      if (match[2]) ports.unshift(Number(match[2]))
    }
  }
  subnets.add('192.168.1')
  subnets.add('192.168.0')

  const hostSuffixes: number[] = []
  for (let i = 2; i <= 40; i++) hostSuffixes.push(i)
  for (let i = 100; i <= 130; i++) hostSuffixes.push(i)

  const candidates: string[] = []
  for (const subnet of subnets) {
    for (const port of Array.from(new Set(ports))) {
      for (const h of hostSuffixes) {
        candidates.push(`http://${subnet}.${h}:${port}`)
      }
    }
  }

  const batchSize = 20
  let checked = 0
  for (let i = 0; i < candidates.length; i += batchSize) {
    const batch = candidates.slice(i, i + batchSize)
    const promises = batch.map(async (url) => {
      try {
        const ctrl = new AbortController()
        const timer = setTimeout(() => ctrl.abort(), 900)
        const res = await fetch(`${url}/api/health`, { signal: ctrl.signal })
        clearTimeout(timer)
        if (res.ok) {
          const data = (await res.json().catch(() => ({}))) as { ok?: boolean }
          if (data.ok) return url
        }
      } catch {
        // unreachable
      }
      return null
    })

    const results = await Promise.all(promises)
    const found = results.find(Boolean)
    if (found) return found
    checked += batch.length
    onProgress?.(checked, candidates.length)
  }
  return null
}

/**
 * آیا هنوز نمی‌دانیم سرور کجاست؟
 *
 * فقط در اپ نیتیو معنا دارد — در مرورگر «خالی» جوابِ درست است، نه یک سؤالِ
 * بی‌مورد از کاربری که همین حالا صفحه را از روی همان سرور باز کرده.
 *
 * در حالت mock هم بی‌معناست: آنجا داده داخل خودِ مرورگر ساخته می‌شود و هیچ
 * سروری در کار نیست، ولی بیلدِ نیتیوِ mock پشتِ صفحه‌ی «آدرس سرور» گیر می‌کرد
 * — آدرسی می‌خواست که وجود ندارد و هیچ‌وقت هم تست نمی‌شد.
 */
export function needsSetup(): boolean {
  if (import.meta.env.VITE_API_MODE !== 'http') return false
  return isNativeApp() && !serverBase()
}

/** یک مسیرِ سرور را به آدرسِ کامل تبدیل می‌کند */
export function apiUrl(path: string): string {
  return serverBase() + path
}

/**
 * آدرس‌های نسبیِ خودِ سرور را مطلق می‌کند.
 *
 * سرور برای فایل و استریم و متن آهنگ `/api/...` برمی‌گرداند. در مرورگر همان
 * درست است؛ در اپ نیتیو باید ریشه جلویش بنشیند. هرچیز دیگری (کاورِ اسپاتیفای،
 * لینکِ منبع) از قبل مطلق است و دست‌نخورده رد می‌شود.
 */
export function absolute<T>(value: T): T {
  return rewrite(value, serverBase())
}

/** همان کار، با ریشه‌ی صریح — تا بشود بدون حالتِ سراسری تستش کرد */
export function rewrite<T>(value: T, base: string): T {
  if (!base) return value
  return walk(value, base) as T
}

function walk(value: unknown, base: string): unknown {
  if (typeof value === 'string') {
    return value.startsWith('/api/') ? base + value : value
  }
  if (Array.isArray(value)) return value.map((item) => walk(item, base))
  if (value && typeof value === 'object') {
    const out: Record<string, unknown> = {}
    for (const [key, item] of Object.entries(value)) out[key] = walk(item, base)
    return out
  }
  return value
}
