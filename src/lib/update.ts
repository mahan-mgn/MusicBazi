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
 * آیا `latest` واقعاً تازه‌تر است؟
 *
 * مقایسه فقط با `versionCode` و فقط عددی. `versionName` برای آدم است و
 * «۱.۱۰» از نظر رشته از «۱.۹» کوچک‌تر می‌شود؛ اگر روزی کسی آن را ملاک
 * بگیرد، بنر برای همیشه روی همان نسخه می‌ماند.
 */
export function isNewer(installed: number, latest: number): boolean {
  return Number.isFinite(latest) && latest > installed
}

export async function checkForUpdate(): Promise<UpdateInfo | null> {
  if (!isNativeApp() || !serverBase()) return null
  const info = await nativeAppInfo()
  if (!info || !info.versionCode) return null

  let data: ReleasePayload | null = null
  try {
    const res = await fetch(apiUrl('/api/release'), { cache: 'no-store' })
    // ۴۰۴ یعنی سرور نسخه‌ای منتشر نکرده (یا قدیمی‌تر از این اندپوینت است) —
    // نه یک خطا؛ نباید کاربر را می‌ترساند
    if (!res.ok) return null
    data = (await res.json()) as ReleasePayload | null
  } catch {
    return null
  }
  if (!data || !isNewer(info.versionCode, data.versionCode)) return null
  if (readStored(DISMISSED_KEY) === String(data.versionCode)) return null

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
export function dismissUpdate(versionCode: number): void {
  writeStored(DISMISSED_KEY, String(versionCode))
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
