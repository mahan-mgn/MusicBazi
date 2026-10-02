import { apiUrl, isNativeApp, serverBase } from './server'
import { nativeAppInfo, openExternal } from './native'
import { readStored, writeStored } from './storage'

/**
 * بررسیِ نسخه‌ی تازه‌ی APK — چون توزیعِ موزیک بازی خودمیزبان است.
 *
 * بدونِ این، کاربرِ روی نسخه‌ی قدیمی هیچ‌وقت نمی‌فهمد چیزی جا انداخته: نه
 * فروشگاهِ اپلیکیشنی هست نه کانالِ دیگری. سرور خودش می‌داند تازه‌ترین APK
 * چیست (`/api/release`) و اپ با `versionCode` نصب‌شده مقایسه می‌کند.
 *
 * روی وب بی‌معناست و `null` می‌دهد: آنجا «بروزرسانی» یعنی رفرشِ صفحه، و
 * سرویس‌ورکر (`registerSW`) همان را خودش می‌گوید. دو پیامِ جدا برای یک اتفاق،
 * فقط گیج‌کننده است.
 */

const GITHUB_REPO = 'mahan-mgn/MusicBazi'
const GITHUB_API_LATEST = `https://api.github.com/repos/${GITHUB_REPO}/releases/latest`

/** نسخه‌ای که کاربر «بعداً» زده — دیگر برای همان نسخه اصرار نمی‌کنیم */
const DISMISSED_KEY = 'update:dismissed'

export interface UpdateInfo {
  versionCode: number
  versionName: string
  notes: string
  /** آدرسِ مطلقِ دانلود؛ null یعنی خبر هست ولی فایلش روی سرور نیست */
  apkUrl: string | null
  bytes: number
  /** نسخه‌ی نصب‌شده، برای نمایشِ «از ۱٫۱ به ۱٫۲» */
  installed: string
}

interface ReleasePayload {
  versionCode: number
  versionName: string
  notes?: string
  apkUrl?: string | null
  bytes?: number
}

/**
 * آیا `latest` واقعاً تازه‌تر است؟ (مقایسه بر اساس versionCode عددی)
 */
export function isNewer(installed: number, latest: number): boolean {
  return Number.isFinite(latest) && latest > installed
}

/**
 * مقایسه نگارش‌های نسخه (semver) به صورت عددی بخش‌به‌بخش.
 * پیشوند v، فاصله‌ها و تگ‌های prerelease را نادیده می‌گیرد و
 * «1.10» را به درستی بزرگ‌تر از «1.9» می‌داند.
 */
export function isNewerVersion(installed: string, latest: string): boolean {
  if (!installed || !latest) return false
  const parse = (v: string) =>
    v
      .replace(/^v/i, '')
      .split(/[-+]/)[0]
      .split('.')
      .map((part) => {
        const n = parseInt(part, 10)
        return Number.isFinite(n) ? n : 0
      })

  const p1 = parse(installed)
  const p2 = parse(latest)
  const len = Math.max(p1.length, p2.length)

  for (let i = 0; i < len; i++) {
    const a = p1[i] ?? 0
    const b = p2[i] ?? 0
    if (b > a) return true
    if (b < a) return false
  }
  return false
}

export async function checkForUpdate(): Promise<UpdateInfo | null> {
  if (!isNativeApp()) return null
  const info = await nativeAppInfo()
  if (!info || !info.versionName) return null

  const dismissed = readStored(DISMISSED_KEY)

  // ۱. بررسی مستقیم GitHub Releases مخزن
  try {
    const ghRes = await fetch(GITHUB_API_LATEST, {
      headers: { Accept: 'application/vnd.github.v3+json' },
      signal: AbortSignal.timeout(5000),
    })
    if (ghRes.ok) {
      const rel = (await ghRes.json()) as {
        id?: number
        tag_name?: string
        name?: string
        body?: string
        html_url?: string
        assets?: Array<{ name?: string; browser_download_url?: string; size?: number }>
      }
      const latestVer = (rel.tag_name || rel.name || '').trim().replace(/^v/i, '')
      if (latestVer && isNewerVersion(info.versionName, latestVer)) {
        if (dismissed === latestVer || dismissed === String(info.versionCode)) return null
        const apkAsset = rel.assets?.find(
          (a) => typeof a.name === 'string' && a.name.toLowerCase().endsWith('.apk'),
        )
        return {
          versionCode: rel.id || info.versionCode,
          versionName: latestVer,
          notes: (rel.body || '').trim().slice(0, 300),
          apkUrl: apkAsset?.browser_download_url || rel.html_url || null,
          bytes: apkAsset?.size ?? 0,
          installed: info.versionName,
        }
      }
      // گیت‌هاب پاسخ داد و نسخه جدیدتری وجود ندارد
      return null
    }
  } catch {
    // آفلاین یا اینترانت یا خطای شبکه گیت‌هاب — به سرور محلی رجوع می‌شود
  }

  // ۲. مسیر پشتیبان: بررسی /api/release سرور محلی (در صورت اتصال)
  if (!serverBase()) return null
  let data: ReleasePayload | null = null
  try {
    const res = await fetch(apiUrl('/api/release'), { cache: 'no-store' })
    if (!res.ok) return null
    data = (await res.json()) as ReleasePayload | null
  } catch {
    return null
  }
  if (!data) return null
  const isServerNewer =
    (data.versionName && isNewerVersion(info.versionName, data.versionName)) ||
    (info.versionCode && data.versionCode && isNewer(info.versionCode, data.versionCode))
  if (!isServerNewer) return null
  if (dismissed === data.versionName || dismissed === String(data.versionCode)) return null

  return {
    versionCode: data.versionCode,
    versionName: data.versionName || String(data.versionCode),
    notes: data.notes ?? '',
    apkUrl: data.apkUrl ? apiUrl(data.apkUrl) : null,
    bytes: data.bytes ?? 0,
    installed: info.versionName,
  }
}

/** «بعداً» — تا نسخه‌ی بعدی سکوت می‌کند */
export function dismissUpdate(version: string | number): void {
  writeStored(DISMISSED_KEY, String(version))
}

/**
 * دانلودِ APK در مرورگرِ سیستم.
 *
 * چرا بیرون از WebView و نه با `fetch` + بلاب؟ چون اندروید یک APK را از داخلِ
 * اپ نصب نمی‌کند (و نباید); باید به «دانلودها» برود و کاربر از همان‌جا نصبش
 * کند. ساده‌ترین راهِ درست، همان است که کاربر خودش انجام می‌داد: بازکردنِ
 * آدرس بیرونِ اپ.
 */
export async function openApkDownload(url: string): Promise<boolean> {
  if (await openExternal(url)) return true
  // مرورگر غیرفعال/حذف‌شده — لینک را لااقل در دسترس بگذار تا کاربر خودش
  // در مرورگر باز کند، به‌جای این‌که دکمه بی‌صدا هیچ کاری نکند
  try {
    await navigator.clipboard.writeText(url)
  } catch {
    // کلیپ‌بورد هم نبود؛ صداکننده false برمی‌گرداند و پیامش «دستی برو» است
  }
  return false
}
